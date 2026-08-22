# backend/tests/test_cpp_bindings.py
"""
Unit test suite for C++ Pybind11 Low-Latency Quant Engine bindings.
Verifies microsecond Order Flow Imbalance (OFI), MicroPrice, VWAP, and EMA.
"""

import sys
import os
import pytest
import numpy as np

# Add C++ build directory to sys.path
cpp_build_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../cpp_engine/build"))
if cpp_build_dir not in sys.path:
    sys.path.insert(0, cpp_build_dir)

def test_cpp_quant_engine_import_and_math():
    try:
        import cpp_quant_engine as cqe
        
        # Test MicroPrice static calculation
        p_micro = cqe.FastAlphaEngine.calculate_micro_price(100.0, 100.2, 500.0, 300.0)
        assert p_micro == pytest.approx(100.125, abs=0.001)

        # Test Order Book Imbalance static calculation
        obi = cqe.FastAlphaEngine.calculate_obi(600.0, 400.0)
        assert obi == pytest.approx(0.20, abs=0.001)

        # Test Fast EMA vector calculation
        prices = [100.0, 102.0, 104.0, 103.0, 105.0]
        ema_vals = cqe.FastAlphaEngine.fast_ema(prices, 9)
        assert len(ema_vals) == len(prices)
        assert ema_vals[-1] > prices[0]

        # Test Real-Time Tick Processing Engine
        engine = cqe.FastAlphaEngine(20)
        tick = cqe.MarketTick(1.0, 100.0, 100.2, 500.0, 300.0, 100.1, 1000.0)
        payload = engine.process_tick(tick)
        
        assert payload.micro_price == pytest.approx(100.125, abs=0.001)
        assert payload.order_book_imbalance == pytest.approx(0.25, abs=0.001)
        assert payload.vwap == pytest.approx(100.1, abs=0.001)
        print("✅ C++ Pybind11 Engine Integration PASSED!")
        
    except ImportError:
        pytest.skip("cpp_quant_engine dynamic library not yet compiled in cpp_engine/build")
