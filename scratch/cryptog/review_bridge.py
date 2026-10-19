"""Bind Engine B to the existing encrypted provider configuration, never expose keys."""
import json
import urllib.request
from .ai_review import SYSTEM, _post
from .config import V2_AI_TIMEOUT_S


def review_options(ai):
    cfg=ai.get_config()
    provider=cfg['provider']
    key=cfg.get('apiKey') or ''
    model=cfg.get('model')
    def post(payload):
        if provider=='DEEPSEEK':return _post(key,model,payload)
        if provider!='GEMINI':raise ValueError('UNSUPPORTED_PROVIDER')
        body={'contents':[{'parts':[{'text':SYSTEM+'\n'+json.dumps(payload,ensure_ascii=False)}]}],
              'generationConfig':{'responseMimeType':'application/json','temperature':0}}
        request=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
            data=json.dumps(body).encode(),headers={'Content-Type':'application/json','x-goog-api-key':key},method='POST')
        with urllib.request.urlopen(request,timeout=V2_AI_TIMEOUT_S) as response:
            data=json.loads(response.read().decode())
        return json.loads(data['candidates'][0]['content']['parts'][0]['text'])
    return {'enabled':cfg.get('enabled') is True,'api_key':key,'post':post if key else None,'model':model,
            'provider':provider}


def review_status(ai):
    try: cfg=ai.get_config()
    except Exception: return {'state':'CONFIG_ERROR','configured':False,'timeoutSeconds':8}
    enabled=cfg.get('enabled') is True
    configured=bool(cfg.get('apiKey'))
    return {'enabled':enabled,'configured':configured,'provider':cfg['provider'],'model':cfg.get('model'),
            'state':'DISABLED' if not enabled else 'READY' if configured else 'MISSING_KEY','timeoutSeconds':8}
