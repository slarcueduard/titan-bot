import os
import json
import gspread
from flask import Flask, request, jsonify
from oauth2client.service_account import ServiceAccountCredentials
from hyperliquid.utils import constants
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from eth_account.signers.local import LocalAccount

app = Flask(__name__)

# --- CONFIGURARE VARIABILE SECRETE (Le vom seta in Render) ---
GOOGLE_JSON = os.environ.get('GOOGLE_JSON_KEY') 
PRIVATE_KEY = os.environ.get('HYPERLIQUID_PRIVATE_KEY')
WALLET_ADDRESS = os.environ.get('HYPERLIQUID_WALLET_ADDRESS')

# --- CONFIGURARE GOOGLE SHEET ---
SHEET_NAME = "TradingTracker"  # Numele fisierului tau Google Sheet
CONFIG_TAB = "CONFIG"          # Tab-ul cu butonul START/STOP
LOG_TAB = "Jurnal"             # Tab-ul unde scriem tranzactiile (sau Sheet1)

def get_sheet_client():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # Convertim string-ul JSON din Render inapoi in dictionar
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        print(f"Eroare Conectare Google: {e}")
        return None

def check_bot_status():
    """Citeste celula B1 din tab-ul CONFIG"""
    try:
        client = get_sheet_client()
        if not client: return "STOP"
        
        sheet = client.open(SHEET_NAME).worksheet(CONFIG_TAB)
        status = sheet.acell('B1').value
        # Daca e gol sau scrie altceva, consideram STOP de siguranta
        if status not in ["START", "STOP"]:
            return "STOP"
        return status
    except Exception as e:
        print(f"Eroare Status Check: {e}")
        return "STOP"

def execute_trade(signal):
    """Executa ordinul pe Hyperliquid"""
    print("Initializare executie...")
    
    # 1. Setup Cont
    account = LocalAccount(PRIVATE_KEY, address=WALLET_ADDRESS)
    
    # 2. Conectare API
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    exchange = Exchange(account, constants.MAINNET_API_URL)
    
    # 3. Parsare Semnal
    coin = signal.get('ticker', 'BTC')   # Default BTC
    action = signal.get('action')        # 'buy' sau 'sell' (mic)
    is_buy = action.lower() == 'buy'
    size_usd = float(signal.get('size_usd', 25)) # Default 25$ daca lipseste
    
    print(f"Semnal Primit: {action.upper()} {coin} | Size: {size_usd}$")

    # 4. Obtine pretul pietei pentru calcul size
    all_mids = info.all_mids()
    price = float(all_mids[coin])
    
    # Calcul Nr. Tokeni (Hyperliquid cere marimea in moneda, nu in USD)
    # Rotunjim la 4-5 zecimale pentru siguranta
    size_token = round(size_usd / price, 5)
    
    print(f"Pret: {price} | Tokeni de cumparat: {size_token}")

    # 5. Executa MARKET ORDER
    # slippage 0.05 inseamna 5% toleranta (ca sa nu pice ordinul daca piata fuge)
    order_result = exchange.market_open(coin, is_buy, size_token, px=price, slippage=0.05)
    
    return order_result

@app.route('/', methods=['GET'])
def home():
    return "Titan Bot v1 is ONLINE. Ready for Webhooks.", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print(f"WEBHOOK PRIMIT: {data}")
    
    if not data:
        return jsonify({"error": "No data"}), 400
    
    # 1. Verificam Butonul din Excel (Kill Switch)
    bot_status = check_bot_status()
    print(f"Status Bot in Excel: {bot_status}")
    
    if bot_status != "START":
        return jsonify({"status": "ignored", "reason": f"Bot is {bot_status} in Excel"}), 200
    
    # 2. Executam Trade-ul
    try:
        result = execute_trade(data)
        print(f"Rezultat Executie: {result}")
        
        # Aici poti adauga codul pentru a scrie rezultatul inapoi in Excel in viitor
        
        return jsonify({"status": "success", "hyperliquid_response": result}), 200
        
    except Exception as e:
        print(f"EROARE CRITICA: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
