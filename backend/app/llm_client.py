# backend/app/llm_client.py
"""
Unified LLM Client Layer — Supports OpenAI and Google Gemini via HTTP API.
No heavy SDK packages required. Includes retry backoff and token/cost counters.
"""

import os
import time
import requests
import logging

logger = logging.getLogger(__name__)

TOTAL_TOKENS_USED = 0
TOTAL_COST_USD = 0.0

def estimate_cost(prompt_tokens: int, completion_tokens: int, provider: str = "openai") -> float:
    """Estimate token costs based on current provider pricing"""
    if provider == "gemini":
        # gemini-1.5-flash: $0.075 / 1M input tokens, $0.30 / 1M output tokens
        return (prompt_tokens * 0.075 / 1_000_000) + (completion_tokens * 0.30 / 1_000_000)
    else:
        # gpt-4o-mini: $0.15 / 1M input tokens, $0.60 / 1M output tokens
        return (prompt_tokens * 0.15 / 1_000_000) + (completion_tokens * 0.60 / 1_000_000)

def get_usage_stats() -> dict:
    """Return accumulated token count and cost estimate"""
    global TOTAL_TOKENS_USED, TOTAL_COST_USD
    openai_key = os.environ.get("OPENAI_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    provider = "none"
    if gemini_key:
        provider = "gemini"
    elif openai_key:
        provider = "openai"
        
    return {
        "total_tokens_used": TOTAL_TOKENS_USED,
        "total_cost_usd": round(TOTAL_COST_USD, 6),
        "provider": provider,
        "available": provider != "none"
    }

def _chat_completion_openai_compat(url: str, headers: dict, model: str, payload_base: dict, attempt: int) -> dict:
    """Attempt OpenAI-compatible endpoint request"""
    try:
        res = requests.post(url, json=payload_base, headers=headers, timeout=30)
        if res.status_code == 200:
            return res.json()
        else:
            logger.warning(f"LLM API compat endpoint returned {res.status_code}: {res.text}")
    except Exception as e:
        logger.warning(f"LLM API compat endpoint error: {e}")
    return None

def _chat_completion_gemini_native(messages: list, gemini_key: str, response_format=None) -> dict:
    """Fallback to native Google Gemini API endpoint"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    
    contents = []
    system_instruction = None
    
    for m in messages:
        role = m["role"]
        content = m["content"]
        if role == "system":
            system_instruction = {"parts": [{"text": content}]}
        else:
            gemini_role = "user" if role == "user" else "model"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": content}]
            })
            
    payload = {"contents": contents}
    if system_instruction:
        payload["systemInstruction"] = system_instruction
        
    generation_config = {}
    if response_format and response_format.get("type") == "json_object":
        generation_config["responseMimeType"] = "application/json"
    if generation_config:
        payload["generationConfig"] = generation_config
        
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=30)
        if res.status_code == 200:
            res_json = res.json()
            # Extract content and usage metadata
            try:
                candidate = res_json["candidates"][0]
                text = candidate["content"]["parts"][0]["text"]
                usage = res_json.get("usageMetadata", {})
                prompt_tokens = usage.get("promptTokenCount", 0)
                completion_tokens = usage.get("candidatesTokenCount", 0)
                
                # Mock OpenAI response format to unify downstream parsing
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": text
                        }
                    }],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens
                    }
                }
            except Exception as parse_err:
                logger.error(f"Failed to parse native gemini response: {parse_err}. Response: {res_json}")
        else:
            logger.warning(f"Gemini native endpoint returned {res.status_code}: {res.text}")
    except Exception as e:
        logger.warning(f"Gemini native endpoint error: {e}")
    return None

def chat_completion(messages: list, tools: list = None, response_format=None, provider: str = None) -> dict:
    """
    Send messages to OpenAI or Gemini and return structured response.
    Returns: {"content": str, "provider": str, "available": bool, "usage": dict}
    """
    global TOTAL_TOKENS_USED, TOTAL_COST_USD
    
    openai_key = os.environ.get("OPENAI_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if not openai_key and not gemini_key:
        return {"provider": "none", "available": False}
        
    if not provider:
        if gemini_key:
            provider = "gemini"
        else:
            provider = "openai"
            
    # Set headers and URL based on provider
    if provider == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {gemini_key}"
        }
        model = "gemini-1.5-flash"
    else:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_key}"
        }
        model = "gpt-4o-mini"
        
    payload = {
        "model": model,
        "messages": messages,
    }
    
    if response_format:
        payload["response_format"] = response_format
        
    if tools:
        payload["tools"] = tools
        
    response = None
    for attempt in range(3):
        # 1. Try OpenAI-compatible endpoint
        response = _chat_completion_openai_compat(url, headers, model, payload, attempt)
        if response:
            break
            
        # 2. If it's Gemini and compat endpoint fails, try Native Gemini API
        if provider == "gemini" and gemini_key:
            logger.info("Attempting fallback to Gemini native endpoint...")
            response = _chat_completion_gemini_native(messages, gemini_key, response_format)
            if response:
                break
                
        # Retry wait with exponential backoff
        time.sleep(2 ** (attempt + 1))
        
    if not response:
        return None
        
    try:
        content = response["choices"][0]["message"]["content"]
        usage = response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        TOTAL_TOKENS_USED += (prompt_tokens + completion_tokens)
        cost = estimate_cost(prompt_tokens, completion_tokens, provider)
        TOTAL_COST_USD += cost
        
        return {
            "content": content,
            "provider": provider,
            "available": True,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "cost_usd": cost
            }
        }
    except Exception as e:
        logger.error(f"Error parsing final LLM response dict: {e}")
        return None
