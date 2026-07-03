import os
from alpaca_trade_api import REST

os.environ['APCA_API_KEY_ID'] = '***'
os.environ['APCA_API_SECRET_KEY'] = '***'

api = REST(
    key_id=os.environ['APCA_API_KEY_ID'],
    secret_key=os.environ['APCA_API_SECRET_KEY'],
    base_url='https://paper-api.alpaca.markets'
)

try:
    account = api.get_account()
    print('Account ID:', account.id)
    print('Status:', account.status)
    print('Portfolio Value: $', float(account.portfolio_value))
    print('Cash: $', float(account.cash))
    print('Buying Power: $', float(account.buying_power))
    print('API Connection: SUCCESS')
except Exception as e:
    print('Error:', e)
