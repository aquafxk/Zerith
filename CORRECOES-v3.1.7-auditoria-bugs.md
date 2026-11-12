# v3.1.7 — bugs criticos da auditoria

1. moderacao: erros apos defer publico usam followup.send (nao send_private_after_defer)
2. ia gerar_imagem: defer ephemeral + followup no erro
3. aniversario config: atualizacao parcial (nao zera cargo/canal omitidos)
4. roles botoes: resposta efemera; nao muta painel publico
5. reaction_remove: fetch_member se fora do cache
6. boas_vindas: volta asyncio.to_thread (sem ProcessPool)
7. video: rmtree em to_thread
8. tickets: history coletado uma vez; fallback reutiliza lista
9. main on_message: mass-mention + automod antes de process_commands
10. social lembrete: nao menciona se usuario perdeu View Channel
