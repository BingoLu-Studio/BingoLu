import sqlite3

conexao = sqlite3.connect("database/bingolu.db")
cursor = conexao.cursor()

print("Atualizando a tabela de pets com novos campos...")

# Adiciona a coluna cep_pet
try:
    cursor.execute("ALTER TABLE pets ADD COLUMN cep_pet TEXT;")
    print("-> Coluna 'cep_pet' adicionada.")
except sqlite3.OperationalError:
    print("-> Coluna 'cep_pet' já existe.")

# Adiciona a coluna faixa_etaria
try:
    cursor.execute("ALTER TABLE pets ADD COLUMN faixa_etaria TEXT;")
    print("-> Coluna 'faixa_etaria' adicionada.")
except sqlite3.OperationalError:
    print("-> Coluna 'faixa_etaria' já existe.")

# Adiciona a coluna nome_dono
try:
    cursor.execute("ALTER TABLE pets ADD COLUMN nome_dono TEXT;")
    print("-> Coluna 'nome_dono' adicionada.")
except sqlite3.OperationalError:
    print("-> Coluna 'nome_dono' já existe.")

conexao.commit()
cursor.close()
conexao.close()
print("Banco de dados pronto!")
