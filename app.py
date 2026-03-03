from flask import Flask, request, jsonify
import os
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

app = Flask(__name__)

# --- CONFIGURARE ---
BOT_STATUS = "START" 

def get_account():
    private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
    if not private_key:
        print("CRITICAL ERROR: 'HYPERLIQUID_PRIVATE_KEY' lipseste!")
        raise ValueError("Missing Key")
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    # Generam obiectul de cont direct din cheia privata
    return eth_account.Account.from_key(private_key)

def get_info():
    return Info(constants.MAINNET_API_URL, skip_ws=True)

def has_open_position(info, address, ticker):
    """
    Verifica daca avem deja o pozitie deschisa pe acest Ticker.
    """
    try:
        user_state = info.user_state(address)
        for position in user_state["assetPositions"]:
            pos_ticker = position["position"]["coin"]
            pos_size = float(position["position"]["szi"])
            if pos_ticker == ticker and abs(pos_size) > 0:
                print(f"!!! POZITIE ACTIVA DETECTATA PE {ticker}: Size {pos_size}")
                return True
        return False
    except Exception as e:
        print(f"Eroare la verificarea pozitiei: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print(f"WEBHOOK PRIMIT: {data}")

    if BOT_STATUS != "START":
        return jsonify({"status": "stopped"}), 200

    ticker = data.get('ticker')
    action = data.get('action') 
    size_usd = float(data.get('size_usd'))
    
    # Rotunjim SL/TP pentru a respecta tick size-ul Hyperliquid
    sl_price = int(round(float(data.get('sl', 0))))
    tp_price = int(round(float(data.get('tp', 0))))
    
    is_buy = (action.lower() == 'buy')

    try:
        # AICI E FIX-UL: Separam generarea contului de crearea exchange-ului
        account = get_account()
        exchange = Exchange(account, constants.MAINNET_API_URL)
        info = get_info()
        
        # Extragem adresa in mod antiglont, direct din contul Ethereum
        address = account.address 
        
        # --- 1. SINGLE SHOT LOGIC (Check Position) ---
        if has_open_position(info, address, ticker):
            msg = f"IGNORAT: Avem deja o pozitie deschisa pe {ticker}. Nu facem stacking."
            print(msg)
            return jsonify({"status": "ignored", "reason": "position_already_open"}), 200

        # --- 2. EXECUTE ENTRY ---
        all_mids = info.all_mids()
        current_price = float(all_mids[ticker])
        size_coin = round(size_usd / current_price, 5)

        print(f">>> EXECUTE ENTRY: {action} {ticker} | Size: {size_coin} BTC | Price: {current_price}")

        order_result = exchange.market_open(
            name=ticker,
            is_buy=is_buy,
            sz=size_coin,
            px=None, 
            slippage=0.01 
        )
        print(f"ENTRY RESULT: {order_result}")
        
        # --- 3. SL & TP ORDERS ---
        if order_result["status"] == "ok":
            is_exit_buy = not is_buy
            
            # STOP LOSS
            if sl_price > 0:
                try:
                    print(f"Placing SL at {sl_price}...")
                    sl_res = exchange.order(
                        name=ticker,
                        is_buy=is_exit_buy,
                        sz=size_coin,
                        limit_px=sl_price, 
                        order_type={"trigger": {"isMarket": True, "triggerPx": sl_price, "tpsl": "sl"}},
                        reduce_only=True
                    )
                    print(f"SL RESPONSE: {sl_res}")
                except Exception as e:
                    print(f"FAILED TO PLACE SL: {e}")

            # TAKE PROFIT
            if tp_price > 0:
                try:
                    print(f"Placing TP at {tp_price}...")
                    tp_res = exchange.order(
                        name=ticker,
                        is_buy=is_exit_buy,
                        sz=size_coin,
                        limit_px=tp_price,
                        order_type={"limit": {"tif": "Gtc"}},
                        reduce_only=True
                    )
                    print(f"TP RESPONSE: {tp_res}")
                except Exception as e:
                    print(f"FAILED TO PLACE TP: {e}")

        return jsonify(order_result), 200

    except Exception as e:
        print(f"EROARE EXECUTIE: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
def health_check():
    return "TITAN BOT ONLINE (FIX ATTRIBUTE ERROR)", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
