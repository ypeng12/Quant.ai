# scratch/test_patterns.py
import sys
import os

# 将 backend 目录添加到 sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from app.data_manager import fetch_and_prepare_data
from app.patterns import analyze_patterns

if __name__ == "__main__":
    print("正在拉取 TSLA 数据来测试形态检测逻辑...")
    try:
        df = fetch_and_prepare_data("TSLA", period="5d")
        df_patterns = analyze_patterns(df)
        
        # 统计检测到的形态
        hammers = df_patterns[df_patterns['Pattern_Hammer']].index
        shooting_stars = df_patterns[df_patterns['Pattern_Shooting_Star']].index
        bullish_eng = df_patterns[df_patterns['Pattern_Bullish_Engulfing']].index
        bearish_eng = df_patterns[df_patterns['Pattern_Bearish_Engulfing']].index
        m_tops = df_patterns[df_patterns['Pattern_M_Top']].index
        w_bottoms = df_patterns[df_patterns['Pattern_W_Bottom']].index
        
        print("\n形态检测统计结果:")
        print(f"  Hammer (锤子): {len(hammers)} 个")
        print(f"  Shooting Star (射击之星): {len(shooting_stars)} 个")
        print(f"  Bullish Engulfing (阳包阴): {len(bullish_eng)} 个")
        print(f"  Bearish Engulfing (阴包阳): {len(bearish_eng)} 个")
        print(f"  M-Top (双顶): {len(m_tops)} 个")
        print(f"  W-Bottom (双底): {len(w_bottoms)} 个")
        
        if len(m_tops) > 0:
            print("\n双顶 M-Top 触发时刻样例:")
            for t in m_tops[:3]:
                print(f"  {t} | 颈线价格: {df_patterns.loc[t, 'M_Neckline']:.2f} | 收盘价: {df_patterns.loc[t, 'Close']:.2f}")
                
        if len(w_bottoms) > 0:
            print("\n双底 W-Bottom 触发时刻样例:")
            for t in w_bottoms[:3]:
                print(f"  {t} | 颈线价格: {df_patterns.loc[t, 'W_Neckline']:.2f} | 收盘价: {df_patterns.loc[t, 'Close']:.2f}")
                
    except Exception as e:
        print(f"测试出错: {e}")
        import traceback
        traceback.print_exc()
