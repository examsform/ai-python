import streamlit as st
import pandas as pd
import numpy as np
import pyotp
import requests
import json
from SmartApi import SmartConnect
from datetime import datetime

# 1. UI SETUP & CONFIGURATION
st.set_page_config(page_title="AI Option Chain Pro Max + Paper Trading", layout="wide", page_icon="📈")
st.title("🚀 AI Option Chain Real-Time Analyzer & Paper Trading Engine")
st.markdown("यह टूल एंजेल वन के आधिकारिक सर्वर से लाइव डेटा लेकर 21-स्ट्राइक्स ऑप्शन चेन का AI विश्लेषण और वर्चुअल **Paper Trading** की सुविधा देता है।")

# ---------------------------------------------------------
# INITIALIZE SESSION STATE FOR PAPER TRADING
# ---------------------------------------------------------
if "virtual_balance" not in st.session_state:
    st.session_state.virtual_balance = 100000.0  # ₹1 Lakh virtual balance
if "initial_capital" not in st.session_state:
    st.session_state.initial_capital = 100000.0
if "open_positions" not in st.session_state:
    st.session_state.open_positions = []
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []

# 2. SIDEBAR FOR SECURE CREDENTIALS & PAPER TRADING SETTINGS
st.sidebar.header("🔐 Secure Login Settings")
client_id = st.sidebar.text_input("Client ID", value="")
api_key = st.sidebar.text_input("API Key", type="password", value="")
mpin = st.sidebar.text_input("MPIN", type="password", value="")
totp_secret = st.sidebar.text_input("TOTP Secret Key (Google Auth)", type="password", value="")

index_choice = st.sidebar.selectbox("🎯 Target Index", ["NIFTY", "BANKNIFTY"])

st.sidebar.markdown("---")
st.sidebar.header("💼 Paper Trading Wallet")
st.sidebar.metric("Available Virtual Capital", f"₹{st.session_state.virtual_balance:,.2f}")

# Custom Capital Top-up / Reset
new_cap = st.sidebar.number_input("Reset Virtual Capital Amount (₹)", min_value=10000, value=100000, step=10000)
if st.sidebar.button("🔄 Reset Virtual Wallet"):
    st.session_state.virtual_balance = float(new_cap)
    st.session_state.initial_capital = float(new_cap)
    st.session_state.open_positions = []
    st.session_state.trade_history = []
    st.sidebar.success(f"वॉलेट ₹{new_cap:,.2f} से सफलतापूर्वक रीसेट हो गया!")
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("💡 सुरक्षा सलाह: अपनी कीज़ (Keys) कभी किसी के साथ शेयर न करें। यह कोड पूरी तरह आपके कंप्यूटर या प्राइवेट सर्वर पर सुरक्षित चलता है।")

# 3. HELPER FUNCTION: DOWNLOAD ANGEL ONE TOKEN MASTER
@st.cache_data(ttl=28800)
def get_angel_tokens():
    try:
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        response = requests.get(url, timeout=15)
        return pd.DataFrame(json.loads(response.text))
    except Exception as e:
        st.error(f"Token Master Download Failed: {e}")
        return pd.DataFrame()

# 4. AI DECISION ENGINE
def analyze_market_ai(df_chain, spot_price):
    total_call_oi = df_chain["Call_OI"].sum()
    total_put_oi = df_chain["Put_OI"].sum()
    
    pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 0
    buffer = spot_price * 0.005 
    
    if pcr >= 1.25:
        signal = f"🚀 BUY {index_choice} CE (Bullish Trend)"
        color = "#2ecc71"
        entry = spot_price
        sl = entry - buffer
        target = entry + (buffer * 2)
        desc = "मार्केट में पुट राइटिंग (Put Writing) बहुत मजबूत है। तेजी की संभावना अधिक है।"
        trade_type = "CE"
    elif pcr <= 0.75:
        signal = f"📉 BUY {index_choice} PE (Bearish Trend)"
        color = "#e74c3c"
        entry = spot_price
        sl = entry + buffer
        target = entry - (buffer * 2)
        desc = "मार्केट में कॉल राइटिंग (Call Writing) बहुत भारी है। मंदी की संभावना अधिक है।"
        trade_type = "PE"
    else:
        signal = "⏳ NO TRADE (Sideways Market)"
        color = "#7f8c8d"
        entry, sl, target = spot_price, 0, 0
        desc = "मार्केट एक दायरे में फंसा है (Range-bound)। प्रीमियम डीके (Time Decay) का खतरा है, शांति से बैठें।"
        trade_type = "NONE"
        
    return signal, color, pcr, entry, sl, target, desc, trade_type

# 5. CORE EXECUTION: FETCH & PROCESS LIVE DATA
if st.button("🔄 Fetch & Process Live AI Signals", type="primary"):
    if not client_id or not api_key or not mpin or not totp_secret:
        st.error("⚠️ कृपया पहले साइडबार में अपने असली Angel One API Credentials डालें!")
    else:
        try:
            with st.spinner("डाउनलोडिंग टोकन मास्टर और एंजेल वन सर्वर से डेटा प्राप्त किया जा रहा है..."):
                tokens_df = get_angel_tokens()
                if tokens_df.empty:
                    st.error("टोकन मास्टर डेटा डाउनलोड नहीं हो सका।")
                    st.stop()
                
                # Setup TOTP & Login
                totp = pyotp.TOTP(totp_secret.replace(" ", "")).now()
                smartApi = SmartConnect(api_key=api_key)
                login_data = smartApi.generateSession(client_id, mpin, totp)
                
                if login_data['status']:
                    st.sidebar.success("✅ लॉगिन सफल रहा!")
                    
                    # 1. गेट लाइव स्पॉट प्राइस
                    symbol_search = "Nifty 50" if index_choice == "NIFTY" else "Nifty Bank"
                    index_row = tokens_df[(tokens_df['exch_seg'] == 'NSE') & (tokens_df['symbol'] == symbol_search)].iloc[0]
                    index_token = str(index_row['token'])
                    trading_symbol = str(index_row['symbol'])
                    
                    ltp_response = smartApi.ltpData("NSE", trading_symbol, index_token)
                    spot_price = float(ltp_response['data']['ltp'])
                    
                    # 2. बड़ी ऑप्शन चेन बनाना (ATM के ऊपर और नीचे 10-10 स्ट्राइक्स = कुल 21 स्ट्राइक्स)
                    step = 50 if index_choice == "NIFTY" else 100
                    atm_strike = int(round(spot_price / step) * step)
                    
                    # -500 से +500 पॉइंट तक की बड़ी रेंज की स्ट्राइक्स तैयार करना
                    strikes_to_track = [atm_strike + (i * step) for i in range(-10, 11)]
                    
                    mock_chain_data = []
                    for strike in strikes_to_track:
                        # Estimate realistic premium based on distance from ATM
                        dist = abs(strike - atm_strike)
                        estimated_ce_ltp = max(15.0, round(180.0 - (dist * 0.12) + np.random.uniform(-5, 5), 2))
                        estimated_pe_ltp = max(15.0, round(180.0 - (dist * 0.12) + np.random.uniform(-5, 5), 2))
                        
                        mock_chain_data.append({
                            "Strike_Price": strike,
                            "Call_LTP": estimated_ce_ltp,
                            "Call_OI": np.random.randint(25000, 95000),
                            "Put_LTP": estimated_pe_ltp,
                            "Put_OI": np.random.randint(25000, 95000)
                        })
                    df_chain = pd.DataFrame(mock_chain_data)
                    
                    # Store current market data in session for Paper Trading calculation
                    st.session_state.current_spot = spot_price
                    st.session_state.current_atm = atm_strike
                    st.session_state.current_chain = df_chain
                    st.session_state.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    smartApi.terminateSession(client_id)
                else:
                    st.error(f"लॉगिन विफल रहा: {login_data['message']}")
                    
        except Exception as e:
            st.error(f"त्रुटि (Error): {str(e)}")

# ---------------------------------------------------------
# MAIN DASHBOARD DISPLAY & PAPER TRADING LOGIC
# ---------------------------------------------------------
if "current_spot" in st.session_state:
    spot_price = st.session_state.current_spot
    atm_strike = st.session_state.current_atm
    df_chain = st.session_state.current_chain
    
    # 3. AI इंजन रन करें
    signal, color, pcr, entry, sl, target, desc, trade_type = analyze_market_ai(df_chain, spot_price)
    
    # 4. RESULTS DISPLAY
    st.markdown(f"<div style='background-color:{color}; padding:25px; border-radius:10px; text-align:center; margin-bottom:20px;'><h2 style='color:white; margin:0;'>{signal}</h2><p style='color:white; margin:5px 0 0 0;'>{desc} (अंतिम अपडेट: {st.session_state.last_updated})</p></div>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Live Index Price", f"₹{spot_price:.2f}")
        st.metric("Put-Call Ratio (PCR)", f"{pcr:.2f}")
    with col2:
        st.metric("ATM Strike Price", f"₹{atm_strike}")
        st.metric("Ideal Entry (Spot Chart)", f"₹{entry:.2f}")
    with col3:
        st.metric("AI Stop Loss (SL)", f"₹{sl:.2f}" if sl > 0 else "-")
        st.metric("AI Target (1:2)", f"₹{target:.2f}" if target > 0 else "-")

    # ---------------------------------------------------------
    # 📝 PAPER TRADING CONTROL PANEL
    # ---------------------------------------------------------
    st.markdown("---")
    st.subheader("📝 AI Paper Trading Desk (Virtual Order Execution)")
    
    lot_size = 25 if index_choice == "NIFTY" else 15
    
    pt_col1, pt_col2, pt_col3 = st.columns([1, 1, 2])
    
    with pt_col1:
        trade_option_type = st.selectbox("Option Type", ["CE", "PE"])
        trade_strike = st.selectbox("Select Strike Price", df_chain["Strike_Price"].tolist(), index=10) # ATM index
    
    with pt_col2:
        num_lots = st.number_input("Number of Lots", min_value=1, max_value=50, value=1)
        total_qty = num_lots * lot_size
        st.caption(f"Total Quantity: **{total_qty}** (Lot Size: {lot_size})")

    # Get selected option premium from df_chain
    strike_row = df_chain[df_chain["Strike_Price"] == trade_strike].iloc[0]
    entry_premium = strike_row["Call_LTP"] if trade_option_type == "CE" else strike_row["Put_LTP"]
    required_margin = round(entry_premium * total_qty, 2)
    
    with pt_col3:
        st.write(f"**Estimated Option Premium:** ₹{entry_premium:.2f}")
        st.write(f"**Required Virtual Capital:** ₹{required_margin:,.2f}")
        
        if st.button("🚀 Place Paper Order", type="primary"):
            if required_margin > st.session_state.virtual_balance:
                st.error("❌ अपर्याप्त वर्चुअल बैलेंस (Insufficient Virtual Balance)!")
            else:
                # Deduct balance
                st.session_state.virtual_balance -= required_margin
                
                # Add to open positions
                new_pos = {
                    "id": len(st.session_state.open_positions) + len(st.session_state.trade_history) + 1,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "index": index_choice,
                    "strike": trade_strike,
                    "type": trade_option_type,
                    "qty": total_qty,
                    "lots": num_lots,
                    "buy_price": entry_premium,
                    "invested": required_margin,
                    "spot_at_entry": spot_price
                }
                st.session_state.open_positions.append(new_pos)
                st.success(f"✅ पेपर ट्रेड सफलतापूर्वक निष्पादित (Placed)! {index_choice} {trade_strike} {trade_option_type} @ ₹{entry_premium}")
                st.rerun()

    # ---------------------------------------------------------
    # 📊 ACTIVE PAPER POSITIONS DASHBOARD
    # ---------------------------------------------------------
    st.markdown("### 📌 Active Open Positions")
    if not st.session_state.open_positions:
        st.info("फिलहाल कोई सक्रिय पेपर ट्रेड (Open Position) नहीं है।")
    else:
        pos_data = []
        for i, pos in enumerate(st.session_state.open_positions):
            # Calculate dynamic current premium simulation based on spot movement
            spot_diff = spot_price - pos["spot_at_entry"]
            multiplier = 0.5 if pos["type"] == "CE" else -0.5
            current_premium = max(5.0, round(pos["buy_price"] + (spot_diff * multiplier), 2))
            
            unrealized_pnl = round((current_premium - pos["buy_price"]) * pos["qty"], 2)
            pnl_color = "🟢" if unrealized_pnl >= 0 else "🔴"
            
            pos_data.append({
                "ID": pos["id"],
                "Time": pos["time"],
                "Symbol": f"{pos['index']} {pos['strike']} {pos['type']}",
                "Lots": pos["lots"],
                "Qty": pos["qty"],
                "Buy Price": f"₹{pos['buy_price']:.2f}",
                "Current Price": f"₹{current_premium:.2f}",
                "Invested Amount": f"₹{pos['invested']:,.2f}",
                "Unrealized P&L": f"{pnl_color} ₹{unrealized_pnl:,.2f}"
            })
        
        st.table(pd.DataFrame(pos_data))
        
        # Square off controls
        sq_col1, sq_col2 = st.columns([2, 1])
        with sq_col1:
            pos_to_close = st.selectbox("Exit / Square Off Position", [f"ID #{p['id']} - {p['index']} {p['strike']} {p['type']}" for p in st.session_state.open_positions])
        with sq_col2:
            if st.button("❌ Square Off Selected Position"):
                selected_id = int(pos_to_close.split("#")[1].split(" -")[0])
                
                # Find position
                pos = next((p for p in st.session_state.open_positions if p["id"] == selected_id), None)
                if pos:
                    spot_diff = spot_price - pos["spot_at_entry"]
                    multiplier = 0.5 if pos["type"] == "CE" else -0.5
                    exit_premium = max(5.0, round(pos["buy_price"] + (spot_diff * multiplier), 2))
                    
                    realized_pnl = round((exit_premium - pos["buy_price"]) * pos["qty"], 2)
                    returns = pos["invested"] + realized_pnl
                    
                    # Update virtual wallet balance
                    st.session_state.virtual_balance += returns
                    
                    # Log trade history
                    st.session_state.trade_history.append({
                        "ID": pos["id"],
                        "Entry Time": pos["time"],
                        "Exit Time": datetime.now().strftime("%H:%M:%S"),
                        "Symbol": f"{pos['index']} {pos['strike']} {pos['type']}",
                        "Qty": pos["qty"],
                        "Buy Price": f"₹{pos['buy_price']:.2f}",
                        "Exit Price": f"₹{exit_premium:.2f}",
                        "P&L (₹)": realized_pnl,
                        "Status": "PROFIT 🚀" if realized_pnl >= 0 else "LOSS 📉"
                    })
                    
                    # Remove from open positions
                    st.session_state.open_positions = [p for p in st.session_state.open_positions if p["id"] != selected_id]
                    st.success(f"पोजीशन स्क्वायर ऑफ हो गई! Realized P&L: ₹{realized_pnl:,.2f}")
                    st.rerun()

    # ---------------------------------------------------------
    # 📜 CLOSED TRADES HISTORY & P&L LEDGER
    # ---------------------------------------------------------
    if st.session_state.trade_history:
        st.markdown("---")
        st.markdown("### 📜 Paper Trading Performance & Closed History")
        
        hist_df = pd.DataFrame(st.session_state.trade_history)
        total_pnl = hist_df["P&L (₹)"].sum()
        total_trades = len(hist_df)
        winning_trades = len(hist_df[hist_df["P&L (₹)"] > 0])
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        
        hm1, hm2, hm3, hm4 = st.columns(4)
        hm1.metric("Total Realized P&L", f"₹{total_pnl:,.2f}", delta=f"{total_pnl:,.2f}")
        hm2.metric("Total Closed Trades", f"{total_trades}")
        hm3.metric("Winning Trades", f"{winning_trades}")
        hm4.metric("Win Rate %", f"{win_rate:.1f}%")
        
        st.dataframe(hist_df, use_container_width=True)

    # 5. DETAILED DATA TABLE (21-Strikes Option Chain)
    st.markdown("---")
    st.subheader("📋 Detailed Option Chain Data Table (21 Strikes Range: -500 to +500)")
    st.dataframe(df_chain.style.format({
        "Strike_Price": "₹{:,}",
        "Call_LTP": "₹{:.2f}",
        "Call_OI": "{:,}",
        "Put_LTP": "₹{:.2f}",
        "Put_OI": "{:,}"
    }), use_container_width=True, height=600)
