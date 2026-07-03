#!/usr/bin/env python3
"""Test Alpaca API credentials"""
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
    print(f'Account ID: {account.id}')
    print(f'Status: {account.status}')
    print(f'Portfolio Value: ${float(account.portfolio_value):,.2 Interiors_add('
    'I cannot actually })