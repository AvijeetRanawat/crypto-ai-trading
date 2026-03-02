#!/usr/bin/env python3
import requests
import sys

try:
    resp = requests.get('http://localhost:8000/api/portfolio/balances', timeout=2)
    data = resp.json()
    
    print('\n🪙  CRYPTO ASSET BALANCES')
    print('=' * 80)
    print()
    
    for balance in data.get('balances', []):
        symbol = balance['symbol']
        qty = balance['total_quantity']
        avg_entry = balance['avg_entry_price']
        current = balance['current_price']
        cost = balance['cost_basis']
        value = balance['current_value']
        pnl = balance['unrealized_pnl']
        pnl_pct = balance['unrealized_pnl_pct']
        
        pnl_sign = '+' if pnl >= 0 else ''
        color = '\033[92m' if pnl >= 0 else '\033[91m'
        reset = '\033[0m'
        
        print(f'{symbol}:')
        print(f'  Quantity: {qty:,.8f}')
        print(f'  Avg Entry: ${avg_entry:,.6f}')
        print(f'  Current:   ${current:,.6f}')
        print(f'  Cost:      ${cost:,.2f}')
        print(f'  Value:     ${value:,.2f}')
        print(f'  P/L:       {color}{pnl_sign}${pnl:,.2f} ({pnl_sign}{pnl_pct:.2f}%){reset}')
        print()
    
    print('=' * 80)
    total_pnl = data['total_unrealized_pnl']
    total_cost = data['total_cost_basis']
    total_value = data['total_current_value']
    total_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    
    pnl_sign = '+' if total_pnl >= 0 else ''
    color = '\033[92m' if total_pnl >= 0 else '\033[91m'
    
    print(f'Total Cost Basis:     ${total_cost:,.2f}')
    print(f'Total Current Value:  ${total_value:,.2f}')
    print(f'Total Unrealized P/L: {color}{pnl_sign}${total_pnl:,.2f} ({pnl_sign}{total_pct:.2f}%){reset}')
    print()
    
except Exception as e:
    print(f'\n❌ Error: {e}')
    print('Make sure the dashboard is running on port 8000\n')
    sys.exit(1)
