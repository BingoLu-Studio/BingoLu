from datetime import datetime
import sqlite3
import os
import re
import math
import requests
import uuid

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    jsonify
)

from werkzeug.utils import secure_filename


# =========================================================
# CONFIGURAÇÃO DO FLASK
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32).hex())

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
# Render persistent disk is mounted at static/uploads; keep both DB and photos there.
PERSISTENT_DIR = os.path.join(ROOT_DIR, "static", "uploads")
os.makedirs(PERSISTENT_DIR, exist_ok=True)
app.config["UPLOAD_FOLDER"] = PERSISTENT_DIR

EXTENSOES_PERMITIDAS = {
    "png",
    "jpg",
    "jpeg"
}

CAMINHO_BANCO = os.path.join(PERSISTENT_DIR, "bingolu.db")


# =========================================================
# ARQUIVOS
# =========================================================

def arquivo_permitido(nome_arquivo):

    return (
        "." in nome_arquivo
        and nome_arquivo.rsplit(".", 1)[1].lower()
        in EXTENSOES_PERMITIDAS
    )


# =========================================================
# BANCO DE DADOS
# =========================================================


def criar_banco():

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                senha TEXT NOT NULL,
                telefone TEXT,
                cidade TEXT,
                latitude REAL,
                longitude REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                descricao TEXT,
                cidade TEXT,
                contato TEXT,
                usuario_id INTEGER,
                imagem TEXT,
                data_postagem TEXT,
                status TEXT,
                especie TEXT,
                sexo TEXT,
                porte TEXT,
                latitude REAL,
                longitude REAL,
                cep_pet TEXT,
                faixa_etaria TEXT,
                nome_dono TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS avistamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pet_id INTEGER,
                local TEXT,
                observacao TEXT,
                data_avistamento TEXT,
                nome_contato TEXT,
                telefone_contato TEXT,
                email_contato TEXT,
                usuario_id INTEGER
            )
        """)

        # Migração para bancos que já existiam.
        colunas_avistamentos = [
            coluna[1]
            for coluna in cursor.execute(
                "PRAGMA table_info(avistamentos)"
            ).fetchall()
        ]

        if "usuario_id" not in colunas_avistamentos:
            cursor.execute("""
                ALTER TABLE avistamentos
                ADD COLUMN usuario_id INTEGER
            """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fotos_pets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pet_id INTEGER NOT NULL,
                imagem TEXT NOT NULL
            )
        """)

        conexao.commit()

    except sqlite3.Error:
        conexao.rollback()
        raise

    finally:
        cursor.close()
        conexao.close()

criar_banco()



# =========================================================
# GEOLOCALIZAÇÃO
# =========================================================

def limpar_cep(cep):

    return re.sub(
        r"\D",
        "",
        cep or ""
    )


def geocodificar_cep(cep):

    """
    Converte um CEP brasileiro em latitude, longitude,
    cidade e UF.

    Fluxo:
    1. ViaCEP valida o CEP e fornece cidade/UF.
    2. ArcGIS localiza o CEP e retorna as coordenadas.
    3. Retorna latitude, longitude, cidade e UF.
    """

    cep_limpo = limpar_cep(cep)

    if len(cep_limpo) != 8:

        print(
            f"[LOCALIZAÇÃO] CEP inválido: {cep}"
        )

        return (
            None,
            None,
            None,
            None
        )

    try:

        # =================================================
        # 1. VIA CEP
        # =================================================

        url_viacep = (
            f"https://viacep.com.br/ws/"
            f"{cep_limpo}/json/"
        )

        resposta_cep = requests.get(
            url_viacep,
            timeout=8
        )

        resposta_cep.raise_for_status()

        dados_cep = resposta_cep.json()

        if dados_cep.get("erro"):

            print(
                f"[LOCALIZAÇÃO] "
                f"CEP não encontrado: {cep}"
            )

            return (
                None,
                None,
                None,
                None
            )

        cidade = (
            dados_cep.get("localidade") or ""
        ).strip()

        uf = (
            dados_cep.get("uf") or ""
        ).strip()

        if not cidade or not uf:

            print(
                "[LOCALIZAÇÃO] "
                "ViaCEP não retornou cidade/UF "
                f"para {cep_limpo}"
            )

            return (
                None,
                None,
                None,
                None
            )

        # =================================================
        # 2. ARCGIS
        # =================================================

        parametros = {

            "SingleLine": (
                f"{cep_limpo}, "
                f"{cidade}, "
                f"{uf}, "
                f"Brasil"
            ),

            "f": "json",

            "maxLocations": 5
        }

        resposta_geo = requests.get(

            "https://geocode.arcgis.com/"
            "arcgis/rest/services/"
            "World/GeocodeServer/"
            "findAddressCandidates",

            params=parametros,

            timeout=10
        )

        resposta_geo.raise_for_status()

        dados_geo = resposta_geo.json()

        candidatos = dados_geo.get(
            "candidates",
            []
        )

        if not candidatos:

            print(
                "[LOCALIZAÇÃO] "
                "Nenhuma coordenada encontrada "
                f"para o CEP {cep_limpo}."
            )

            return (
                None,
                None,
                None,
                None
            )

        # =================================================
        # 3. ESCOLHER CANDIDATO
        # =================================================

        for candidato in candidatos:

            localizacao = candidato.get(
                "location",
                {}
            )

            latitude = localizacao.get("y")

            longitude = localizacao.get("x")

            if (
                latitude is None
                or longitude is None
            ):
                continue

            try:

                latitude = float(latitude)

                longitude = float(longitude)

            except (
                TypeError,
                ValueError
            ):

                continue

            score = candidato.get(
                "score",
                0
            )

            if score < 80:
                continue

            print(
                "[LOCALIZAÇÃO] "
                f"CEP {cep_limpo} -> "
                f"{latitude}, {longitude} "
                f"(score: {score}) "
                f"| cidade: {cidade}/{uf}"
            )

            return (
                latitude,
                longitude,
                cidade,
                uf
            )

        # =================================================
        # 4. FALHA SEGURA
        # =================================================

        print(
            "[LOCALIZAÇÃO] "
            "Nenhuma coordenada confiável "
            f"encontrada para o CEP {cep_limpo}."
        )

        return (
            None,
            None,
            None,
            None
        )

    except requests.RequestException as erro:

        print(
            "[LOCALIZAÇÃO] "
            "Erro de comunicação com serviço externo: "
            f"{erro}"
        )

        return (
            None,
            None,
            None,
            None
        )

    except (
        ValueError,
        KeyError,
        TypeError
    ) as erro:

        print(
            "[LOCALIZAÇÃO] "
            "Resposta inválida da geolocalização: "
            f"{erro}"
        )

        return (
            None,
            None,
            None,
            None
        )

    except Exception as erro:

        print(
            "[LOCALIZAÇÃO] "
            "Erro inesperado: "
            f"{erro}"
        )

        return (
            None,
            None,
            None,
            None
        )


# =========================================================
# DISTÂNCIA GEOGRÁFICA
# =========================================================

def calcular_distancia(
    lat1,
    lon1,
    lat2,
    lon2
):

    """
    Calcula a distância em quilômetros
    entre duas coordenadas usando Haversine.
    """

    coordenadas = (
        lat1,
        lon1,
        lat2,
        lon2
    )

    if any(
        valor is None
        for valor in coordenadas
    ):

        return float("inf")

    try:

        lat1 = float(lat1)
        lon1 = float(lon1)

        lat2 = float(lat2)
        lon2 = float(lon2)

    except (
        TypeError,
        ValueError
    ):

        return float("inf")

    if (
        lat1 == 0.0
        or lon1 == 0.0
        or lat2 == 0.0
        or lon2 == 0.0
    ):

        return float("inf")

    raio_terra = 6371.0

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)

    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1

    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    return raio_terra * c


# =========================================================
# PÁGINA INICIAL
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form[
            "email"
        ].strip()

        senha = request.form[
            "senha"
        ]

        conexao = sqlite3.connect(
            CAMINHO_BANCO,
            timeout=10
        )

        cursor = conexao.cursor()

        cursor.execute("""
            SELECT *
            FROM usuarios
            WHERE email = ?
            AND senha = ?
        """, (
            email,
            senha
        ))

        usuario = cursor.fetchone()

        cursor.close()

        conexao.close()

        if usuario:

            session[
                "usuario_id"
            ] = usuario[0]

            session[
                "usuario_nome"
            ] = usuario[1]

            return redirect(
                "/feed"
            )

        return render_template(
            "login.html",
            erro="E-mail ou senha incorretos. Verifique os dados e tente novamente.",
            email=email
        )

    return render_template(
        "login.html",
        erro=None,
        email=""
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# =========================================================
# CADASTRO
# =========================================================

@app.route(
    "/cadastro",
    methods=["GET", "POST"]
)
def cadastro():

    if request.method == "POST":

        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip()
        senha = request.form.get("senha", "")
        telefone_formatado = request.form.get("telefone", "").strip()
        cep_formatado = request.form.get("cep", "").strip()
        cidade_informada = request.form.get("cidade", "").strip()

        telefone_limpo = re.sub(r"\D", "", telefone_formatado)
        cep_limpo = limpar_cep(cep_formatado)

        formulario = {
            "nome": nome,
            "email": email,
            "telefone": telefone_formatado,
            "cep": cep_formatado,
            "cidade": cidade_informada
        }

        def erro_cadastro(mensagem):
            return render_template(
                "cadastro.html",
                erro=mensagem,
                formulario=formulario
            )

        # -------------------------------------------------
        # VALIDAÇÕES DOS CAMPOS
        # -------------------------------------------------

        if len(nome) < 3:
            return erro_cadastro(
                "Informe seu nome completo ou um nome com pelo menos 3 caracteres."
            )

        if len(nome) > 80:
            return erro_cadastro(
                "O nome deve ter no máximo 80 caracteres."
            )

        if not re.match(
            r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[^\s@]+\.[^\s@]+$",
            email
        ):
            return erro_cadastro(
                "E-mail inválido. Confira o endereço informado."
            )

        if len(senha) < 6:
            return erro_cadastro(
                "A senha deve possuir pelo menos 6 caracteres."
            )

        if len(senha) > 128:
            return erro_cadastro(
                "A senha deve ter no máximo 128 caracteres."
            )

        if len(telefone_limpo) not in (10, 11):
            return erro_cadastro(
                "Telefone inválido. Informe o DDD e o número, com 10 ou 11 dígitos."
            )

        if len(cep_limpo) != 8:
            return erro_cadastro(
                "CEP inválido. Informe exatamente 8 números."
            )

        # Evita consultar os serviços de CEP quando o e-mail já existe.
        conexao = sqlite3.connect(CAMINHO_BANCO, timeout=10)
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT 1 FROM usuarios WHERE LOWER(email) = LOWER(?)",
            (email,)
        )
        email_existente = cursor.fetchone()
        cursor.close()
        conexao.close()

        if email_existente:
            return erro_cadastro(
                "Este e-mail já está cadastrado. Utilize outro endereço ou entre na sua conta."
            )

        # -------------------------------------------------
        # LOCALIZAÇÃO AUTOMÁTICA PELO CEP
        # Mantém a validação ViaCEP + ArcGIS já existente.
        # A cidade gravada continua vindo do CEP validado.
        # -------------------------------------------------

        (
            latitude,
            longitude,
            cidade,
            uf
        ) = geocodificar_cep(cep_limpo)

        if (
            latitude is None
            or longitude is None
            or cidade is None
            or uf is None
        ):
            return erro_cadastro(
                "Não foi possível validar e localizar este CEP. Confira os números e tente novamente."
            )

        # -------------------------------------------------
        # SALVAMENTO
        # -------------------------------------------------

        conexao = sqlite3.connect(CAMINHO_BANCO, timeout=10)
        cursor = conexao.cursor()

        try:
            cursor.execute("""
                INSERT INTO usuarios (
                    nome,
                    email,
                    senha,
                    telefone,
                    cidade,
                    latitude,
                    longitude
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                nome,
                email,
                senha,
                telefone_formatado,
                cidade,
                latitude,
                longitude
            ))
            conexao.commit()

        except sqlite3.IntegrityError:
            conexao.rollback()
            cursor.close()
            conexao.close()
            return erro_cadastro(
                "Este e-mail já está cadastrado. Utilize outro endereço ou entre na sua conta."
            )

        except sqlite3.Error:
            conexao.rollback()
            cursor.close()
            conexao.close()
            return erro_cadastro(
                "Não foi possível concluir o cadastro agora. Tente novamente."
            )

        cursor.close()
        conexao.close()

        return redirect("/login")

    return render_template(
        "cadastro.html",
        erro=None,
        formulario={}
    )


# =========================================================
# FEED
# =========================================================

@app.route("/feed")
def feed():

    if "usuario_id" not in session:

        return redirect("/login")

    especie = request.args.get(
        "especie"
    )

    aba = request.args.get(
        "aba",
        "geral"
    )

    if aba not in (
        "geral",
        "alertas"
    ):

        aba = "geral"

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    # -----------------------------------------------------
    # LOCALIZAÇÃO DO USUÁRIO
    # -----------------------------------------------------

    cursor.execute("""
        SELECT latitude, longitude
        FROM usuarios
        WHERE id = ?
    """, (
        session["usuario_id"],
    ))

    usuario_geo = cursor.fetchone()

    user_lat = (
        usuario_geo[0]
        if usuario_geo
        else None
    )

    user_lng = (
        usuario_geo[1]
        if usuario_geo
        else None
    )

    # -----------------------------------------------------
    # BUSCA DOS PETS
    # -----------------------------------------------------

    query = """
        SELECT
            id,
            nome,
            descricao,
            cidade,
            contato,
            imagem,
            data_postagem,
            status,
            usuario_id,
            especie,
            sexo,
            porte,
            latitude,
            longitude,
            faixa_etaria,
            nome_dono
        FROM pets
        WHERE status = 'Perdido'
    """

    parametros = []

    # -----------------------------------------------------
    # FILTRO DE ESPÉCIE
    # -----------------------------------------------------

    if especie == "Outro":

        query += """
            AND (
                especie NOT IN (
                    'Canino',
                    'Felino',
                    'Ave'
                )
                OR especie IS NULL
                OR TRIM(especie) = ''
            )
        """

    elif especie in (
        "Canino",
        "Felino",
        "Ave"
    ):

        query += """
            AND especie = ?
        """

        parametros.append(
            especie
        )

    query += """
        ORDER BY id DESC
    """

    cursor.execute(
        query,
        tuple(parametros)
    )

    todos_os_pets = (
        cursor.fetchall()
    )

    cursor.close()

    conexao.close()

    # -----------------------------------------------------
    # FILTRAGEM POR DISTÂNCIA
    # -----------------------------------------------------

    pets_filtrados = []

    for pet in todos_os_pets:

        pet_lat = pet[12]

        pet_lng = pet[13]

        distancia = calcular_distancia(
            user_lat,
            user_lng,
            pet_lat,
            pet_lng
        )

        if distancia == float("inf"):

            continue

        # -------------------------------------------------
        # ALERTAS
        # 0 até 2 km
        # -------------------------------------------------

        if aba == "alertas":

            if distancia > 2.0:

                continue

        # -------------------------------------------------
        # FEED REGIONAL
        # Acima de 2 km e até 5 km
        # -------------------------------------------------

        else:

            if distancia <= 2.0:

                continue

            if distancia > 5.0:

                continue

        pet_lista = list(
            pet
        )

        pet_lista.append(
            round(
                distancia,
                1
            )
        )

        pets_filtrados.append(
            pet_lista
        )

    # -----------------------------------------------------
    # MAIS PRÓXIMOS PRIMEIRO
    # -----------------------------------------------------

    pets_filtrados.sort(
        key=lambda pet: pet[16]
    )

    return render_template(
        "feed.html",
        pets=pets_filtrados,
        especie_ativa=especie,
        aba_ativa=aba
    )


# =========================================================
# PETS ENCONTRADOS
# =========================================================

@app.route("/encontrados")
def encontrados():

    if "usuario_id" not in session:

        return redirect("/login")

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            id,
            nome,
            descricao,
            cidade,
            contato,
            imagem,
            data_postagem,
            status,
            usuario_id,
            especie,
            sexo,
            porte
        FROM pets
        WHERE status = 'Encontrado'
        ORDER BY id DESC
    """)

    pets = cursor.fetchall()

    cursor.close()

    conexao.close()

    return render_template(
        "encontrados.html",
        pets=pets
    )


# =========================================================
# MEUS PETS
# =========================================================

@app.route("/meus_posts")
def meus_posts():

    if "usuario_id" not in session:

        return redirect("/login")

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    # IMPORTANTE:
    # Esta ordem precisa ser mantida porque
    # o meus_posts.html utiliza esses índices.
    cursor.execute("""
        SELECT
            id,
            nome,
            descricao,
            cidade,
            contato,
            imagem,
            data_postagem,
            status
        FROM pets
        WHERE usuario_id = ?
        AND status = 'Perdido'
        ORDER BY id DESC
    """, (
        session["usuario_id"],
    ))

    pets = cursor.fetchall()

    cursor.close()

    conexao.close()

    return render_template(
        "meus_posts.html",
        pets=pets
    )


# =========================================================
# GALERIA DE FOTOS
# =========================================================

@app.route(
    "/fotos_pet/<int:id_pet>"
)
def fotos_pet(id_pet):

    if "usuario_id" not in session:

        return jsonify({
            "fotos": []
        }), 401

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT imagem
        FROM pets
        WHERE id = ?
    """, (
        id_pet,
    ))

    pet = cursor.fetchone()

    if not pet:

        cursor.close()

        conexao.close()

        return jsonify({
            "fotos": []
        }), 404

    fotos = []

    if pet[0]:

        fotos.append(
            "/static/uploads/"
            + pet[0]
        )

    cursor.execute("""
        SELECT imagem
        FROM fotos_pets
        WHERE pet_id = ?
        ORDER BY id ASC
    """, (
        id_pet,
    ))

    fotos_adicionais = (
        cursor.fetchall()
    )

    cursor.close()

    conexao.close()

    for foto in fotos_adicionais:

        if foto[0]:

            fotos.append(
                "/static/uploads/"
                + foto[0]
            )

    return jsonify({
        "fotos": fotos
    })


# =========================================================
# MARCAR COMO ENCONTRADO
# =========================================================

@app.route(
    "/marcar_encontrado/<int:id_post>"
)
def marcar_encontrado(id_post):

    if "usuario_id" not in session:

        return redirect("/login")

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    cursor.execute("""
        UPDATE pets
        SET status = 'Encontrado'
        WHERE id = ?
        AND usuario_id = ?
    """, (
        id_post,
        session["usuario_id"]
    ))

    conexao.commit()

    cursor.close()

    conexao.close()

    return redirect(
        "/meus_posts"
    )


# =========================================================
# EDITAR POSTAGEM
# =========================================================

@app.route(
    "/editar_post/<int:id_post>",
    methods=["GET", "POST"]
)
def editar_post(id_post):

    if "usuario_id" not in session:

        return redirect("/login")

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    if request.method == "POST":

        nome = request.form[
            "nome"
        ].strip()

        descricao = request.form[
            "descricao"
        ].strip()

        cidade = request.form[
            "cidade"
        ].strip()

        contato = request.form[
            "contato"
        ].strip()

        cursor.execute("""
            UPDATE pets
            SET
                nome = ?,
                descricao = ?,
                cidade = ?,
                contato = ?
            WHERE id = ?
            AND usuario_id = ?
        """, (
            nome,
            descricao,
            cidade,
            contato,
            id_post,
            session["usuario_id"]
        ))

        conexao.commit()

        cursor.close()

        conexao.close()

        return redirect(
            "/meus_posts"
        )

    cursor.execute("""
        SELECT
            id,
            nome,
            descricao,
            cidade,
            contato
        FROM pets
        WHERE id = ?
        AND usuario_id = ?
    """, (
        id_post,
        session["usuario_id"]
    ))

    pet = cursor.fetchone()

    cursor.close()

    conexao.close()

    return render_template(
        "editar_post.html",
        pet=pet
    )


# =========================================================
# EXCLUIR POSTAGEM
# =========================================================

@app.route(
    "/excluir_post/<int:id_post>"
)
def excluir_post(id_post):

    if "usuario_id" not in session:

        return redirect("/login")

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    cursor.execute("""
        DELETE FROM pets
        WHERE id = ?
        AND usuario_id = ?
    """, (
        id_post,
        session["usuario_id"]
    ))

    conexao.commit()

    cursor.close()

    conexao.close()

    return redirect(
        "/meus_posts"
    )


# =========================================================
# NOVA POSTAGEM DE PET
# =========================================================

@app.route(
    "/post_pet",
    methods=["GET", "POST"]
)
def post_pet():

    if "usuario_id" not in session:

        return redirect("/login")

    if request.method == "POST":

        nome = request.form[
            "nome"
        ].strip()

        descricao = request.form[
            "descricao"
        ].strip()

        contato = request.form[
            "contato"
        ].strip()

        data_postagem = (
            datetime.now().strftime(
                "%d/%m/%Y"
            )
        )

        status = "Perdido"

        nome_dono = session.get(
            "usuario_nome",
            "Usuário Registrado"
        )

        especie = request.form.get(
            "especie"
        )

        sexo = request.form.get(
            "sexo"
        )

        faixa_etaria = (
            request.form.get(
                "faixa_etaria"
            )
        )

        # -------------------------------------------------
        # CATEGORIAS OFICIAIS
        # -------------------------------------------------

        categorias_validas = {
            "Canino",
            "Felino",
            "Ave",
            "Outro"
        }

        if especie not in categorias_validas:

            return (
                "Selecione uma categoria "
                "válida para o animal."
            )

        porte = (
            request.form.get(
                "porte"
            )
            if especie == "Canino"
            else None
        )

        # -------------------------------------------------
        # CEP
        # -------------------------------------------------

        cep_form = request.form[
            "cep"
        ].strip()

        cep_limpo = limpar_cep(
            cep_form
        )

        if len(cep_limpo) != 8:

            return (
                "CEP inválido. "
                "Informe exatamente "
                "8 números."
            )

        # -------------------------------------------------
        # FOTOS
        # -------------------------------------------------

        fotos = [
            foto
            for foto in request.files.getlist(
                "fotos"
            )
            if foto and foto.filename
        ]

        # 3 obrigatórias + até 2 extras.
        if len(fotos) < 3 or len(fotos) > 5:

            return (
                "É obrigatório enviar "
                "de 3 a 5 fotos do animal."
            )

        for foto in fotos:

            if (
                not foto
                or not foto.filename
            ):

                return (
                    "As 3 fotos do animal "
                    "são obrigatórias."
                )

            if not arquivo_permitido(
                foto.filename
            ):

                return (
                    "Formato de imagem inválido."
                )

        os.makedirs(
            app.config[
                "UPLOAD_FOLDER"
            ],
            exist_ok=True
        )

        nomes_fotos = []

        caminhos_fotos = []

        try:

            # -------------------------------------------------
            # SALVAR ARQUIVOS
            # -------------------------------------------------

            for foto in fotos:

                extensao = (
                    foto.filename
                    .rsplit(
                        ".",
                        1
                    )[1]
                    .lower()
                )

                nome_arquivo = (
                    f"{uuid.uuid4().hex}"
                    f".{extensao}"
                )

                caminho_foto = os.path.join(
                    app.config[
                        "UPLOAD_FOLDER"
                    ],
                    nome_arquivo
                )

                foto.save(
                    caminho_foto
                )

                nomes_fotos.append(
                    nome_arquivo
                )

                caminhos_fotos.append(
                    caminho_foto
                )

            # -------------------------------------------------
            # GEOLOCALIZAÇÃO DO PET
            # -------------------------------------------------

            (
                latitude_pet,
                longitude_pet,
                cidade_pet,
                uf_pet
            ) = geocodificar_cep(
                cep_limpo
            )

            if (
                latitude_pet is None
                or longitude_pet is None
                or cidade_pet is None
                or uf_pet is None
            ):

                raise ValueError(
                    "Não foi possível localizar "
                    "o CEP do desaparecimento."
                )

            # -------------------------------------------------
            # SALVAMENTO
            # -------------------------------------------------

            conexao = sqlite3.connect(
                CAMINHO_BANCO,
                timeout=10
            )

            cursor = conexao.cursor()

            try:

                # Primeira foto = principal
                cursor.execute("""
                    INSERT INTO pets (
                        nome,
                        descricao,
                        cidade,
                        contato,
                        usuario_id,
                        imagem,
                        data_postagem,
                        status,
                        especie,
                        sexo,
                        porte,
                        latitude,
                        longitude,
                        cep_pet,
                        faixa_etaria,
                        nome_dono
                    )
                    VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?
                    )
                """, (
                    nome,
                    descricao,
                    cidade_pet,
                    contato,
                    session["usuario_id"],
                    nomes_fotos[0],
                    data_postagem,
                    status,
                    especie,
                    sexo,
                    porte,
                    latitude_pet,
                    longitude_pet,
                    cep_form,
                    faixa_etaria,
                    nome_dono
                ))

                id_pet = (
                    cursor.lastrowid
                )

                # Fotos 2 em diante = galeria
                fotos_galeria = [
                    (
                        id_pet,
                        nome_foto
                    )
                    for nome_foto
                    in nomes_fotos[1:]
                ]

                cursor.executemany("""
                    INSERT INTO fotos_pets (
                        pet_id,
                        imagem
                    )
                    VALUES (?, ?)
                """, fotos_galeria)

                conexao.commit()

            except Exception:

                conexao.rollback()

                raise

            finally:

                cursor.close()

                conexao.close()

        except Exception as erro:

            # Remove arquivos caso o processo falhe.
            for caminho_foto in (
                caminhos_fotos
            ):

                try:

                    os.remove(
                        caminho_foto
                    )

                except OSError:

                    pass

            if isinstance(
                erro,
                ValueError
            ):

                return str(erro)

            print(
                "[POST PET] "
                "Erro ao salvar anúncio: "
                f"{erro}"
            )

            return (
                "Não foi possível publicar "
                "o anúncio. Tente novamente."
            )

        return redirect(
            "/feed"
        )

    return render_template(
        "post_pet.html"
    )


# =========================================================
# INFORMAR AVISTAMENTO
# =========================================================

@app.route(
    "/avistar/<int:id_pet>",
    methods=["GET", "POST"]
)
def avistar(id_pet):

    if "usuario_id" not in session:
        return redirect("/login")

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT id
        FROM pets
        WHERE id = ?
        AND status = 'Perdido'
    """, (id_pet,))

    pet = cursor.fetchone()

    cursor.close()
    conexao.close()

    if not pet:
        return redirect("/feed")

    if request.method == "POST":

        local = request.form.get(
            "local", ""
        ).strip()

        observacao = request.form.get(
            "observacao", ""
        ).strip()

        nome_contato = request.form.get(
            "nome_contato", ""
        ).strip()

        telefone_contato = request.form.get(
            "telefone_contato", ""
        ).strip()

        email_contato = request.form.get(
            "email_contato", ""
        ).strip()

        if not all((
            local,
            observacao,
            nome_contato,
            telefone_contato
        )):
            return (
                "Preencha o endereço, a descrição, "
                "o nome e o telefone para enviar."
            ), 400

        data_avistamento = datetime.now().strftime(
            "%d/%m/%Y"
        )

        conexao = sqlite3.connect(
            CAMINHO_BANCO,
            timeout=10
        )

        cursor = conexao.cursor()

        try:
            cursor.execute("""
                INSERT INTO avistamentos (
                    pet_id,
                    local,
                    observacao,
                    data_avistamento,
                    nome_contato,
                    telefone_contato,
                    email_contato,
                    usuario_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                id_pet,
                local,
                observacao,
                data_avistamento,
                nome_contato,
                telefone_contato,
                email_contato,
                session["usuario_id"]
            ))

            conexao.commit()

        except sqlite3.Error as erro:
            conexao.rollback()

            print(
                "[AVISTAMENTO] Erro ao salvar:",
                erro
            )

            return (
                "Não foi possível enviar o avistamento. "
                "Tente novamente."
            ), 500

        finally:
            cursor.close()
            conexao.close()

        return redirect(
            "/meus_avistamentos?aba=enviados"
        )

    return render_template(
        "avistar.html",
        id_pet=id_pet
    )


# =========================================================
# CENTRAL DE AVISTAMENTOS
# =========================================================

@app.route("/meus_avistamentos")
def meus_avistamentos():

    if "usuario_id" not in session:
        return redirect("/login")

    usuario_id = session["usuario_id"]

    aba = request.args.get(
        "aba", "recebidos"
    )

    if aba not in ("recebidos", "enviados"):
        aba = "recebidos"

    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )

    cursor = conexao.cursor()

    # Avistamentos feitos por outras pessoas
    # sobre os pets do usuário.
    cursor.execute("""
        SELECT
            avistamentos.id,
            pets.nome,
            pets.imagem,
            avistamentos.local,
            avistamentos.observacao,
            avistamentos.data_avistamento,
            avistamentos.nome_contato,
            avistamentos.telefone_contato,
            avistamentos.email_contato
        FROM avistamentos
        INNER JOIN pets
            ON avistamentos.pet_id = pets.id
        WHERE pets.usuario_id = ?
        ORDER BY avistamentos.id DESC
    """, (usuario_id,))

    recebidos = cursor.fetchall()

    # Avistamentos enviados pelo usuário logado.
    cursor.execute("""
        SELECT
            avistamentos.id,
            pets.nome,
            pets.imagem,
            avistamentos.local,
            avistamentos.observacao,
            avistamentos.data_avistamento,
            avistamentos.nome_contato,
            avistamentos.telefone_contato,
            avistamentos.email_contato
        FROM avistamentos
        INNER JOIN pets
            ON avistamentos.pet_id = pets.id
        WHERE avistamentos.usuario_id = ?
        ORDER BY avistamentos.id DESC
    """, (usuario_id,))

    enviados = cursor.fetchall()

    cursor.close()
    conexao.close()

    return render_template(
        "meus_avistamentos.html",
        recebidos=recebidos,
        enviados=enviados,
        aba=aba
    )


# EXECUÇÃO
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        debug=False
    )