from flask import Flask, request, jsonify
import os
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
import threading # NOU: Importam threading pentru Background Tasks

app = Flask(__name__)

BOT_STATUS = "START" 

def get_account():
    private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
    if not private_key:
        print("CRITICAL ERROR: 'HYPERLIQUID_PRIVATE_KEY' lipseste!")
        raise ValueError("Missing Key")
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    return eth_account.Account.from_key(private_key)

def get_info():
    return Info(constants.MAINNET_API_URL, skip_ws=True)

def has_open_position(info, address, ticker):
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

# ==========================================
# THE HEAVY LIFTING (Background Worker)
# ==========================================
def execute_trade_logic(data):
    try:
        ticker = data.get('ticker')
        action = data.get('action') 
        size_usd = float(data.get('size_usd'))
        
        sl_price = int(round(float(data.get('sl', 0))))
        tp_price = int(round(float(data.get('tp', 0))))
        
        is_buy = (action.lower() == 'buy')

        account = get_account()
        exchange = Exchange(account, constants.MAINNET_API_URL)
        info = get_info()
        address = account.address 
        
        if has_open_position(info, address, ticker):
            print(f"IGNORAT: Avem deja o pozitie deschisa pe {ticker}.")
            return

        all_mids = info.all_mids()
        current_price = float(all_mids[ticker])
        size_coin = round(size_usd / current_price, 5)

        print(f">>> EXECUTE ENTRY: {action} {ticker} | Size: {size_coin} BTC")
        order_result = exchange.market_open(name=ticker, is_buy=is_buy, sz=size_coin, px=None, slippage=0.01)
        
        if order_result.get("status") == "ok":
            is_exit_buy = not is_buy
            
            if sl_price > 0:
                try:
                    exchange.order(name=ticker, is_buy=is_exit_buy, sz=size_coin, limit_px=sl_price, order_type={"trigger": {"isMarket": True, "triggerPx": sl_price, "tpsl": "sl"}}, reduce_only=True)
                except Exception as e:
                    print(f"FAILED TO PLACE SL: {e}")

            if tp_price > 0:
                try:
                    exchange.order(name=ticker, is_buy=is_exit_buy, sz=size_coin, limit_px=tp_price, order_type={"limit": {"tif": "Gtc"}}, reduce_only=True)
                except Exception as e:
                    print(f"FAILED TO PLACE TP: {e}")

    except Exception as e:
        print(f"EROARE EXECUTIE BACKGROUND: {e}")


# ==========================================
# THE FRONT DESK (Fast Ack pt TradingView)
# ==========================================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print(f"\nWEBHOOK PRIMIT: {data}")

    if BOT_STATUS != "START":
        return jsonify({"status": "stopped"}), 200

    # Delegam treaba grea catre un Thread separat
    trade_thread = threading.Thread(target=execute_trade_logic, args=(data,))
    trade_thread.start()

    # Raspundem INSTANT la TradingView ca sa evitam eroarea de Timeout
    return jsonify({"status": "fast_ack", "message": "Semnal receptionat, executie in fundal"}), 200

@app.route('/', methods=['GET'])
def health_check():
    return "TITAN BOT ONLINE (FAST ACK ACTIVE)", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
