from flask import Flask, request, jsonify
import os
import json
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

app = Flask(__name__)

# --- CONFIGURARE ---
# Aici punem "START" fortat, ca sa ignoram eroarea de Google Sheets
BOT_STATUS = "START" 

def get_exchange():
    private_key = os.getenv("PRIVATE_KEY")
    account: LocalAccount = eth_account.Account.from_key(private_key)
    # Folosim MAINNET pentru bani reali
    exchange = Exchange(account, constants.MAINNET_API_URL)
    return exchange

@app.route('/webhook', methods=['POST'])
def webhook():
    # 1. Verificam daca a ajuns mesajul
    data = request.json
    print(f"WEBHOOK PRIMIT: {data}")

    # 2. Verificam Statusul (BYPASS GOOGLE - Mereu START)
    if BOT_STATUS != "START":
        print("Bot is STOPPED (Hardcoded).")
        return jsonify({"status": "stopped"}), 200

    ticker = data.get('ticker')
    action = data.get('action') # buy / sell
    size_usd = float(data.get('size_usd'))
    trade_id = data.get('trade_id')
    
    # SL/TP logic can be added later, for now we execute Market Order
    is_buy = (action.lower() == 'buy')

    try:
        exchange = get_exchange()
        
        # Obtinem pretul curent pentru a calcula size-ul in monede (ex: 0.001 BTC)
        info = exchange.info.meta()
        price = 0
        # O logica simplificata pentru a lua pretul (in productie e mai complex, dar pt test e ok)
        # Hyperliquid API requires coin size, not USD size usually via SDK helpers
        # Dar SDK-ul are market_open care accepta sz (size). 
        # Vom incerca executia directa.
        
        print(f"EXECUTING {action} on {ticker} for ${size_usd}")
        
        # Executam Market Order
        # Atentie: Hyperliquid cere "coin size", nu USD. 
        # Trebuie sa stim pretul ca sa impartim. 
        # Pentru acest test rapid, SDK-ul gestioneaza conversia daca folosim update_leverage si market_open corect?
        # NU. Trebuie calculat manual in Python sau trimis "sz" corect.
        # Daca Titan trimite size_usd, noi trebuie sa convertim aici.
        
        # PENTRU TESTUL TAU ACUM: 
        # Vom face conversia simpla.
        all_mids = exchange.info.all_mids()
        current_price = float(all_mids[ticker])
        size_coin = size_usd / current_price
        
        # Rotunjim la precizia corecta (Hyperliquid cere de obicei 4-5 zecimale pt BTC)
        size_coin = round(size_coin, 5)

        print(f"Pret: {current_price}, Size Coin: {size_coin}")

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
    return "TITAN BOT IS ONLINE (NO GOOGLE)", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
