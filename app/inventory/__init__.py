"""Распродажа инвентаря Steam: продать по рынку или разобрать на самоцветы (B-16).

Субмодули:
  fees       — комиссия маркета в целых копейках
  plan       — правила выбора sell_bid / sell_ask / grind / skip
  items      — разбор инвентаря 753/6 в предметы
  badges     — максимумы значков из GetBadges
  market     — orderbook, sellitem, ajaxgrindintogoo
  state      — data/games/ids/inventory_sale/
  run        — оркестровка, точка входа для CLI
"""
