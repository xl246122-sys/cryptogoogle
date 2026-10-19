"""Frozen production/replay input contract. These describe existing windows, not a retune."""
INPUT_CONTRACT = {'version':'inputs-v2.1','windows':{'1m':47,'5m':47,'15m':95,'1h':47,'4h':47},
                  'contextWindow':300,'emaSeed':'SMA','bollingerDdof':0,'rsi':'WILDER','atr':'WILDER',
                  'ruleVersion':'short-horizon-v2','executionVersion':'settlement-v2.1','costVersion':'cost-v2.1'}
