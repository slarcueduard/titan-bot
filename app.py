from flask import Flask, request, jsonify
import os
import json
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

app = Flask(__name__)

# --- CONFIGURARE ---
BOT_STATUS = "START" 

def get_exchange():
    # MODIFICARE: Acum cautam exact numele pe care l-ai pus tu in Render
    private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
    
    # Debugging (fara a afisa cheia)
    if not private_key:
        print("CRITICAL ERROR: 'HYPERLIQUID_PRIVATE_KEY' nu este setata in Render!")
        raise ValueError("Missing Key")
    else:
        print("Key found inside Render environment. Connecting...")
    
    # Curatare cheie
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
        
    account: LocalAccount = eth_account.Account.from_key(private_key)
    exchange = Exchange(account, constants.MAINNET_API_URL)
    return exchange

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print(f"WEBHOOK PRIMIT: {data}")

    if BOT_STATUS != "START":
        print("Bot is STOPPED.")
        return jsonify({"status": "stopped"}), 200

    ticker = data.get('ticker')
    action = data.get('action') 
    size_usd = float(data.get('size_usd'))
    is_buy = (action.lower() == 'buy')

    try:
        exchange = get_exchange()
        
        # Conversie
        all_mids = exchange.info.all_mids()
        current_price = float(all_mids[ticker])
        size_coin = size_usd / current_price
        size_coin = round(size_coin, 5)

        print(f"EXECUTING {action} {ticker} @ {current_price}. Size: {size_coin}")

        order_result = exchange.market_open(
            name=ticker,
            is_buy=is_buy,
            sz=size_coin,
            px=None, 
            slippage=0.01 
        )
        
        print(f"ORDER RESULT: {order_result}")
        return jsonify(order_result), 200

    except Exception as e:
        print(f"EROARE EXECUTIE: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
def health_check():
    return "TITAN BOT ONLINE - READY", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
