import sqlite3

CAMINHO_BANCO = "database/bingolu.db"

conexao = sqlite3.connect(CAMINHO_BANCO)
cursor = conexao.cursor()

print("==============================================")
print("LIMPANDO DADOS DE TESTE")
print("==============================================")

cursor.execute("DELETE FROM avistamentos")
cursor.execute("DELETE FROM pets")
cursor.execute("DELETE FROM usuarios")

conexao.commit()

print()
print("Avistamentos: todos removidos.")
print("Pets: todos removidos.")
print("Usuários: todos removidos.")
print()
print("Estrutura do banco preservada.")
print("Nenhuma tabela foi apagada.")
print()
print("==============================================")
print("LIMPEZA CONCLUÍDA")
print("==============================================")

cursor.close()
conexao.close()
