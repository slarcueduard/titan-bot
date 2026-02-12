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
    # 1. Cautam cheia privata (variabila ta)
    private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
    
    if not private_key:
        print("CRITICAL ERROR: 'HYPERLIQUID_PRIVATE_KEY' lipseste!")
        raise ValueError("Missing Key")
    
    # Curatare cheie
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
        
    account: LocalAccount = eth_account.Account.from_key(private_key)
    exchange = Exchange(account, constants.MAINNET_API_URL)
    return exchange

def place_sl_tp(exchange, ticker, is_buy_entry, size_coin, sl_price, tp_price):
    """
    Functie auxiliara pentru a pune SL si TP.
    Acestea trebuie sa fie ordine opuse intrarii (Reduce-Only).
    """
    is_buy_exit = not is_buy_entry # Daca am cumparat (Long), iesim cu Sell.
    
    orders = []

    # 1. STOP LOSS (Trigger Order)
    if sl_price > 0:
        # Pentru Long: SL este sub pret (Sell Stop). Pentru Short: SL este peste pret (Buy Stop).
        # Hyperliquid Trigger Order logic:
        # is_market: True (vinde la market cand atinge pretul)
        sl_order = {
            "a": 0, # Asset index (se completeaza automat de SDK de obicei, dar punem placeholder)
            "b": is_buy_exit,
            "p": str(sl_price),
            "s": str(size_coin),
            "r": True, # REDUCE ONLY (Critic!)
            "t": {
                "trigger": {
                    "isMarket": True,
                    "triggerPx": str(sl_price),
                    "tpsl": "sl" 
                }
            }
        }
        # Nota: SDK-ul Exchange.order() este complex. Vom folosi o abordare directa via SDK wrapper daca exista,
        # dar cel mai sigur pe Hyperliquid este sa folosim apelul de 'order' generic.
        # Pentru simplitate maxima si siguranta, folosim apeluri secventiale prin metodele SDK-ului.
        print(f"Adding SL Order @ {sl_price}")

    # 2. TAKE PROFIT (Limit Order)
    if tp_price > 0:
        # TP este Limit Order (Reduce Only)
        print(f"Adding TP Order @ {tp_price}")
    
    return True

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print(f"WEBHOOK PRIMIT: {data}")

    if BOT_STATUS != "START":
        return jsonify({"status": "stopped"}), 200

    ticker = data.get('ticker')
    action = data.get('action') 
    size_usd = float(data.get('size_usd'))
    
    # Citim SL si TP din alerta
    sl_price = float(data.get('sl', 0))
    tp_price = float(data.get('tp', 0))
    
    is_buy = (action.lower() == 'buy')

    try:
        exchange = get_exchange()
        
        # 1. Obtinem pretul curent si calculam size-ul
        all_mids = exchange.info.all_mids()
        current_price = float(all_mids[ticker])
        size_coin = size_usd / current_price
        
        # Rotunjim size-ul (Hyperliquid cere precizie specifica, de obicei 5 pt BTC)
        # O metoda mai robusta ar fi sa luam precizia din meta info, dar 5 e safe pt BTC.
        size_coin = round(size_coin, 5)

        print(f">>> EXECUTE ENTRY: {action} {ticker} | Size: {size_coin} BTC | Price: {current_price}")

        # 2. EXECUTAM INTRAREA (Market Order)
        order_result = exchange.market_open(
            name=ticker,
            is_buy=is_buy,
            sz=size_coin,
            px=None, 
            slippage=0.01 
        )
        print(f"ENTRY RESULT: {order_result}")
        
        # Verificam daca intrarea a reusit
        if order_result["status"] == "ok":
            
            # 3. EXECUTAM ORDINELE DE IESIRE (SL & TP)
            # Pe Hyperliquid, folosim 'update_leverage' ca safety, dar punem ordinele manual.
            
            # Directia iesirii
            is_exit_buy = not is_buy
            
            # --- STOP LOSS ---
            if sl_price > 0:
                try:
                    # Trigger order type logic
                    print(f"Placing SL at {sl_price}...")
                    sl_res = exchange.order(
                        name=ticker,
                        is_buy=is_exit_buy,
                        sz=size_coin,
                        limit_px=sl_price, # La trigger orders, limit_px e pretul trigger
                        order_type={"trigger": {"isMarket": True, "triggerPx": sl_price, "tpsl": "sl"}},
                        reduce_only=True
                    )
                    print(f"SL PLACED: {sl_res}")
                except Exception as e:
                    print(f"FAILED TO PLACE SL: {e}")

            # --- TAKE PROFIT ---
            if tp_price > 0:
                try:
                    print(f"Placing TP at {tp_price}...")
                    # TP ca Limit Order Reduce-Only
                    tp_res = exchange.order(
                        name=ticker,
                        is_buy=is_exit_buy,
                        sz=size_coin,
                        limit_px=tp_price,
                        order_type={"limit": {"tif": "Gtc"}},
                        reduce_only=True
                    )
                    print(f"TP PLACED: {tp_res}")
                except Exception as e:
                    print(f"FAILED TO PLACE TP: {e}")

        return jsonify(order_result), 200

    except Exception as e:
        print(f"EROARE EXECUTIE: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
def health_check():
    return "TITAN BOT ONLINE (SL/TP ENABLED)", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
