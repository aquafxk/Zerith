# Ferramentas de descoberta adicionadas

- `cog_loader.py`: descoberta e carregamento independente de extensões em `cogs/`.
- `scripts/ai_discovery.py`: consulta modelos Groq e Gemini sem bloquear o event loop.
- `package.py`: gera ZIP excluindo segredos, bancos, caches e ambientes virtuais.

## Uso

```bash
python scripts/ai_discovery.py
python package.py
```

O carregador é fornecido como utilitário. A inicialização atual do projeto mantém sua lista de extensões em `main.py`; a substituição por descoberta automática deve ser feita após validar dependências e ordem de carregamento dos Cogs.

Configure `GROQ_API_KEY` e `GEMINI_API_KEY` no `.env`. Nunca distribua o `.env`.
