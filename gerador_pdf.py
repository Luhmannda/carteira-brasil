# GERADOR CARTEIRA BRASIL
"""
gerador_pdf.py — monta o PDF "Carteira Brasil" a partir de dataset.json e
editorial.json, renderizando via Chromium headless, e roda o checador
estrutural sobre o mesmo HTML.

Uso:
    python3 gerador_pdf.py <dataset.json> <editorial.json> <saida.pdf> <relatorio_checador.json>

Só usa stdlib (json, sys, os, subprocess, html, math, glob, unicodedata,
tempfile, re). Não faz rede, não lê nada além dos dois JSON de entrada.
"""

import sys
import os
import io
import json
import glob
import math
import html
import subprocess
import unicodedata
import tempfile

# --------------------------------------------------------------------------
# Chromium
# --------------------------------------------------------------------------

CHROME_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def localizar_chromium():
    if os.path.isfile(CHROME_PATH):
        return CHROME_PATH
    candidatos = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    if candidatos:
        return candidatos[0]
    raise RuntimeError("Chromium não encontrado em /opt/pw-browsers/chromium-*/chrome-linux/chrome")


# --------------------------------------------------------------------------
# Formatação pt-BR
# --------------------------------------------------------------------------

MENOS = "−"  # sinal de menos tipográfico (U+2212), nunca hífen


def _agrupa_milhar(intpart):
    rev = intpart[::-1]
    partes = [rev[i:i + 3] for i in range(0, len(rev), 3)]
    return ".".join(partes)[::-1]


def _num_valido(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def fmt_numero(v, casas=2):
    """Número em pt-BR, sinal natural (só aparece se negativo). None -> n/d."""
    f = _num_valido(v)
    if f is None:
        return "n/d"
    neg = f < 0
    f = abs(f)
    s = f"{f:.{casas}f}"
    intpart, _, decpart = s.partition(".")
    intpart = _agrupa_milhar(intpart)
    out = f"{intpart},{decpart}" if casas > 0 else intpart
    if neg:
        out = MENOS + out
    return out


def fmt_var(v, casas=2, unidade="%"):
    """Variação em pt-BR com sinal SEMPRE explícito (+/−). Zero exato sem sinal."""
    f = _num_valido(v)
    if f is None:
        return "n/d"
    if f > 0:
        sinal = "+"
    elif f < 0:
        sinal = MENOS
    else:
        sinal = ""
    corpo = fmt_numero(abs(f), casas)
    return f"{sinal}{corpo} {unidade}" if unidade else f"{sinal}{corpo}"


def fmt_int(v):
    f = _num_valido(v)
    if f is None:
        return "n/d"
    return _agrupa_milhar(str(abs(int(round(f)))))


# --------------------------------------------------------------------------
# Leitura -> slug / cor
# --------------------------------------------------------------------------

def slug_leitura(leitura):
    if not leitura:
        return "sem-dados"
    nfkd = unicodedata.normalize("NFKD", leitura)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().lower().replace(" ", "-")


LEITURA_VAR = {
    "favoravel": "--fav",
    "atencao": "--aten",
    "neutro": "--neut",
    "sem-dados": "--semd",
}


def cor_leitura(leitura):
    slug = slug_leitura(leitura)
    varname = LEITURA_VAR.get(slug, "--semd")
    return f"var({varname})"


# --------------------------------------------------------------------------
# Cor: mistura e contraste (para o heatmap)
# --------------------------------------------------------------------------

def hex_para_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_para_hex(rgb):
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def mistura(hex_a, hex_b, t):
    t = max(0.0, min(1.0, t))
    ra, ga, ba = hex_para_rgb(hex_a)
    rb, gb, bb = hex_para_rgb(hex_b)
    return rgb_para_hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def _luminancia_relativa(hexcor):
    r, g, b = hex_para_rgb(hexcor)

    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _razao_contraste(h1, h2):
    l1 = _luminancia_relativa(h1)
    l2 = _luminancia_relativa(h2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def texto_para_fundo(fundo_hex, escuro="#0B2340", claro="#FFFFFF"):
    if _razao_contraste(fundo_hex, escuro) >= _razao_contraste(fundo_hex, claro):
        return escuro
    return claro


# --------------------------------------------------------------------------
# Paleta — validada para visão de cores; lida de dataset["paleta"] quando
# presente, com fallback para os hexes validados abaixo.
# --------------------------------------------------------------------------

PALETA_FALLBACK = {
    "pos":  "#007EA4",
    "neg":  "#972700",
    "fav":  "#007EA4",
    "aten": "#B45309",
    "neut": "#2B3138",
    "semd": "#A9AFB5",
}


def _hex_valido(v):
    if not isinstance(v, str):
        return False
    s = v.strip()
    if len(s) != 7 or not s.startswith("#"):
        return False
    try:
        int(s[1:], 16)
        return True
    except ValueError:
        return False


def resolver_paleta(dataset):
    bruta = dataset.get("paleta")
    paleta = dict(PALETA_FALLBACK)
    if isinstance(bruta, dict):
        for chave in PALETA_FALLBACK:
            v = bruta.get(chave)
            if _hex_valido(v):
                paleta[chave] = v.strip()
    return paleta


# --------------------------------------------------------------------------
# Helpers HTML / data-campo
# --------------------------------------------------------------------------

def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def valor_cru_str(v):
    return "null" if v is None else str(v)


def span_campo(campo, valor_cru, texto, classe=""):
    classe_attr = f' class="{esc(classe)}"' if classe else ""
    return (f'<span data-campo="{esc(campo)}" data-valor="{esc(valor_cru_str(valor_cru))}"'
            f'{classe_attr}>{esc(texto)}</span>')


def get(d, *chave, default=None):
    cur = d
    for k in chave:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is None:
            return None
    return cur


# --------------------------------------------------------------------------
# Carregamento robusto do dataset/editorial
# --------------------------------------------------------------------------

def carregar_json(caminho):
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def montar_contexto(dataset, editorial):
    ativos = dataset.get("ativos") or []
    if not isinstance(ativos, list):
        ativos = []
    return {
        "paleta": resolver_paleta(dataset),
        "edicao": dataset.get("edicao"),
        "D": dataset.get("D"),
        "ancoras": dataset.get("ancoras") or {},
        "cobertura": dataset.get("cobertura") or {},
        "macro": dataset.get("macro") or {},
        "carteira": dataset.get("carteira") or {},
        "ibov": dataset.get("ibov") or {},
        "amplitude": dataset.get("amplitude") or {},
        "ativos": ativos,
        "titulo_edicao": editorial.get("titulo_edicao") or "Carteira Brasil",
        "conclusoes": editorial.get("conclusoes") or [],
        "destaques": editorial.get("destaques") or [],
        "destaques_complemento": editorial.get("destaques_complemento"),
        "notas": editorial.get("notas") or [],
        "agenda": editorial.get("agenda") or [],
        "agenda_nota": editorial.get("agenda_nota"),
        "legenda": editorial.get("legenda") or [],
        "metodologia": editorial.get("metodologia") or [],
        "glossario": editorial.get("glossario") or [],
        "fontes": editorial.get("fontes") or [],
        "rodape": editorial.get("rodape"),
    }


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------

def css_paleta(paleta):
    """Bloco :root com a paleta de dados (lida de dataset['paleta'], com
    fallback para os hexes validados). As cores de texto das pílulas
    (--txt-*) são calculadas pela função de contraste, nunca fixas —
    importante porque --semd agora é clara e precisa de texto escuro."""
    txt_fav = texto_para_fundo(paleta["fav"], escuro="#1A2733", claro="#FFFFFF")
    txt_aten = texto_para_fundo(paleta["aten"], escuro="#1A2733", claro="#FFFFFF")
    txt_neut = texto_para_fundo(paleta["neut"], escuro="#1A2733", claro="#FFFFFF")
    txt_semd = texto_para_fundo(paleta["semd"], escuro="#1A2733", claro="#FFFFFF")
    return f"""/* ==== PALETA ==== */
:root {{
  --navy:   #0B2340;
  --gold:   #C9A227;
  --fundo:  #FFFFFF;
  --texto:  #1A2733;
  --cinza:  #5A6875;
  --linha:  #D8DEE5;

  --pos:  {paleta['pos']};
  --neg:  {paleta['neg']};
  --fav:  {paleta['fav']};
  --aten: {paleta['aten']};
  --neut: {paleta['neut']};
  --semd: {paleta['semd']};

  --txt-fav:  {txt_fav};
  --txt-aten: {txt_aten};
  --txt-neut: {txt_neut};
  --txt-semd: {txt_semd};
}}
/* ==== FIM PALETA ==== */"""


CSS_BASE = """
@page { size: A4; margin: 0; }

* { box-sizing: border-box; }

html, body {
  margin: 0; padding: 0;
  font-family: 'DejaVu Sans', 'Noto Sans', sans-serif;
  color: var(--texto);
  background: var(--fundo);
  font-size: 8.5pt;
}

.page {
  width: 210mm;
  height: 297mm;
  box-sizing: border-box;
  padding: 14mm 15mm;
  position: relative;
  overflow: hidden;
}
/* Conteúdo ancorado no topo: NUNCA usar flex/justify-content para
   centralizar ou distribuir sobra verticalmente (isso empurra o miolo
   para baixo e faz o rodapé real ser cortado pelo overflow:hidden). */
.page:not(:last-of-type) { page-break-after: always; }

h1, h2, h3, p, ul, ol, table { margin: 0; padding: 0; }

.cabecalho {
  display: flex; justify-content: space-between; align-items: flex-end;
  border-bottom: 1.2mm solid var(--gold);
  padding-bottom: 3mm; margin-bottom: 5mm;
}
.cabecalho h1 { font-size: 20pt; color: var(--navy); font-weight: 700; letter-spacing: 0.3pt; }
.cabecalho .meta { text-align: right; font-size: 8.5pt; color: var(--cinza); line-height: 1.4; }
.cabecalho .meta b { color: var(--navy); }

.aviso-edicao {
  font-size: 8.5pt; color: var(--navy); background: #F4EFDD;
  border-left: 3px solid var(--gold); padding: 2.6mm 3mm; margin-bottom: 4mm;
}

.secao-titulo {
  font-size: 9.5pt; color: var(--navy); font-weight: 700;
  border-bottom: 0.4mm solid var(--linha); padding-bottom: 1.4mm; margin-bottom: 2.6mm;
  text-transform: uppercase; letter-spacing: 0.4pt;
}

.conclusoes { list-style: none; margin-bottom: 5mm; }
.conclusoes li { position: relative; padding-left: 4mm; margin-bottom: 2.4mm; font-size: 9.8pt; line-height: 1.45; }
.conclusoes li::before { content: "\\25CF"; color: var(--gold); position: absolute; left: 0; font-size: 6.5pt; top: 0.8mm; }

.cartoes-macro { display: flex; gap: 2.6mm; margin-bottom: 5mm; }
.cartao-macro {
  flex: 1; border: 0.3mm solid var(--linha); border-radius: 1.5mm; padding: 3.4mm 2.4mm;
  background: #FAFBFC;
}
.cartao-macro .rot { font-size: 7.2pt; color: var(--cinza); text-transform: uppercase; letter-spacing: 0.3pt; }
.cartao-macro .val { font-size: 13pt; color: var(--navy); font-weight: 700; margin: 0.5mm 0; }
.cartao-macro .sub { font-size: 7.5pt; color: var(--cinza); line-height: 1.2; }
.cartao-macro .delta { font-size: 7.8pt; font-weight: 700; }

.faixa-amplitude {
  display: flex; gap: 5mm; align-items: center; border: 0.3mm solid var(--linha);
  border-radius: 1.5mm; padding: 4mm 3.5mm; margin-bottom: 5mm; background: #FAFBFC;
}
.faixa-amplitude .num { font-size: 14pt; font-weight: 700; color: var(--navy); }
.confronto-janelas { display: flex; gap: 4mm; flex: 1; }
.confronto-janelas .item { flex: 1; text-align: center; }
.confronto-janelas .item .rot { font-size: 7.5pt; color: var(--cinza); }
.confronto-janelas .item .linha { font-size: 9.5pt; margin-top: 1.4mm; }

.notas-edicao { font-size: 8.2pt; color: var(--cinza); line-height: 1.42; }
.notas-edicao .secao-titulo { font-size: 8.5pt; }
.notas-edicao .notas-cols { display: flex; gap: 5mm; }
.notas-edicao .notas-cols .col { flex: 1; min-width: 0; }
.notas-edicao ul { list-style: none; }
.notas-edicao li { padding-left: 3mm; position: relative; margin-bottom: 1.6mm; }
.notas-edicao li::before { content: "\\2013"; position: absolute; left: 0; }

.pos { color: var(--pos); }
.neg { color: var(--neg); }

.pilula {
  display: inline-block; padding: 0.3mm 1.8mm; border-radius: 3mm;
  font-size: 7.4pt; font-weight: 700; white-space: nowrap;
}
.pilula.favoravel { background: var(--fav);  color: var(--txt-fav); }
.pilula.atencao   { background: var(--aten); color: var(--txt-aten); }
.pilula.neutro    { background: var(--neut); color: var(--txt-neut); }
.pilula.sem-dados { background: var(--semd); color: var(--txt-semd); }

/* ---------- Página 2 ---------- */
.bloco { margin-bottom: 2.2mm; }
.bloco:last-child { margin-bottom: 0; }
.bloco .subtitulo { font-size: 7.6pt; color: var(--cinza); margin-bottom: 1.2mm; }

table.heatmap { width: 100%; border-collapse: collapse; font-size: 7.3pt; }
table.heatmap th { text-align: left; font-size: 7pt; color: var(--cinza); padding: 0.5mm 1mm; border-bottom: 0.3mm solid var(--linha); }
table.heatmap th.num, table.heatmap td.num { text-align: center; }
table.heatmap td { padding: 0.42mm 1mm; border-bottom: 0.2mm solid #EEF1F4; }
table.heatmap td.ticker { font-weight: 700; color: var(--navy); white-space: nowrap; }
table.heatmap td.ticker span.emp { font-weight: 400; color: var(--cinza); }
.celula-hm { display: block; text-align: center; border-radius: 0.8mm; padding: 0.4mm 0; font-weight: 700; }

.barras-wrap { position: relative; }
.barras-legenda { display: flex; justify-content: space-between; font-size: 7.2pt; color: var(--cinza); margin-bottom: 0.8mm; }
.barra-linha { display: flex; align-items: center; height: 4mm; }
.barra-linha .rot { width: 40mm; font-size: 7pt; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 1.5mm; }
.barra-linha .rot b { color: var(--navy); }
.barra-linha .rot span.emp { color: var(--cinza); }
.barra-campo { position: relative; flex: 1; height: 3.2mm; background: #F7F8F9; border-radius: 0.6mm; overflow: visible; }
.barra-zero { position: absolute; top: -0.4mm; bottom: -0.4mm; left: 50%; width: 0.28mm; background: var(--linha); }
.barra-ibov { position: absolute; top: -0.4mm; bottom: -0.4mm; width: 0.28mm; border-left: 0.35mm dashed var(--gold); }
.barra-valor { position: absolute; top: 0; height: 100%; border-radius: 0.5mm; }
.barra-rotulo { position: absolute; top: 50%; transform: translateY(-50%); font-size: 6.8pt; font-weight: 700; white-space: nowrap; }
.barra-nd { font-size: 7.2pt; color: var(--cinza); font-style: italic; }

.comparativo { display: flex; gap: 4mm; }
.painel-comp { flex: 1; border: 0.3mm solid var(--linha); border-radius: 1.5mm; padding: 1.7mm 2.6mm; }
.painel-comp .titulo { font-size: 7.8pt; font-weight: 700; color: var(--navy); }
.painel-comp .escala { font-size: 6.9pt; color: var(--cinza); margin-bottom: 1.1mm; }
.comp-barra-linha { display: flex; align-items: center; height: 4.4mm; }
.comp-barra-linha .rot { width: 18mm; font-size: 7.3pt; }
.comp-nd { font-size: 7.6pt; color: var(--cinza); font-style: italic; padding: 1.5mm 0; }

/* ---------- Página 3 ---------- */
.cards-destaque { display: flex; flex-direction: column; gap: 3.2mm; }
.card-destaque { border: 0.3mm solid var(--linha); border-radius: 1.6mm; padding: 3mm 3.6mm; position: relative; }
.card-destaque .topo { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.8mm; }
.card-destaque .topo .titulo { font-size: 10pt; font-weight: 700; color: var(--navy); }
.card-destaque .corpo p { font-size: 8.8pt; line-height: 1.55; margin-bottom: 1.8mm; }
.card-destaque .corpo b { color: var(--navy); }
.card-destaque .fonte { font-size: 7.6pt; color: var(--cinza); margin-top: 1.2mm; }
.card-destaque .fonte a { color: var(--navy); }

.complemento { border: 0.3mm dashed var(--linha); border-radius: 1.6mm; padding: 3mm 3.6mm; margin-top: 3.2mm; }
.complemento .titulo { font-size: 9.5pt; font-weight: 700; color: var(--navy); margin-bottom: 1.8mm; }
.complemento ul { list-style: none; }
.complemento li { font-size: 8.4pt; padding-left: 3.4mm; position: relative; margin-bottom: 1.6mm; line-height: 1.4; }
.complemento li::before { content: "\\2192"; position: absolute; left: 0; color: var(--gold); }
.complemento .comp-cols { display: flex; gap: 6mm; }
.complemento .comp-cols .col { flex: 1; min-width: 0; }

/* ---------- Página 4 ---------- */
table.quadro { width: 100%; border-collapse: collapse; font-size: 7.4pt; table-layout: fixed; }
table.quadro th {
  text-align: left; font-size: 6.9pt; color: #fff; background: var(--navy);
  padding: 1.4mm 1.1mm; font-weight: 700;
}
table.quadro td { padding: 1.5mm 1.1mm; border-bottom: 0.2mm solid var(--linha); vertical-align: top; overflow-wrap: break-word; line-height: 1.16; }
table.quadro tr:nth-child(even) td { background: #F7F9FB; }
table.quadro td.num { text-align: right; }
table.quadro td.num span { white-space: nowrap; }
table.quadro td.ticker { font-weight: 700; color: var(--navy); white-space: nowrap; }
/* "fechamento D" não pode quebrar no meio da palavra. */
table.quadro td.ref { white-space: nowrap; }
/* Data da agenda em uma linha só: "2026-07-30", nunca "2026-07-" / "30". */
table.agenda td:first-child { white-space: nowrap; }
table.quadro td.contexto { font-size: 6.9pt; color: var(--cinza); line-height: 1.16; }
table.quadro .pilula { font-size: 6.6pt; padding: 0.2mm 1.1mm; }

/* ---------- Página 5 ---------- */
table.agenda { width: 100%; border-collapse: collapse; font-size: 8pt; margin-bottom: 2.4mm; }
table.agenda th { text-align: left; font-size: 7.3pt; color: var(--cinza); border-bottom: 0.3mm solid var(--linha); padding: 0.8mm 1mm; }
table.agenda td { padding: 0.8mm 1mm; border-bottom: 0.2mm solid #EEF1F4; }

.agenda-nota { font-size: 7.6pt; color: var(--cinza); line-height: 1.3; margin-bottom: 2.4mm; font-style: italic; }

.legenda-lista { display: flex; flex-direction: column; gap: 0.9mm; margin-bottom: 2.4mm; }
.legenda-item { display: flex; align-items: baseline; gap: 2mm; font-size: 7.8pt; }

.metodologia-lista { list-style: none; margin-bottom: 2.4mm; column-count: 2; column-gap: 6mm; }
.metodologia-lista li { font-size: 7.6pt; line-height: 1.3; padding-left: 3mm; position: relative; margin-bottom: 0.8mm; break-inside: avoid; }
.metodologia-lista li::before { content: "\\2022"; position: absolute; left: 0; color: var(--gold); }

.glossario-cols { display: flex; gap: 6mm; margin-bottom: 2.4mm; }
.glossario-cols .col { flex: 1; }
.glossario-item { font-size: 7.6pt; margin-bottom: 1.2mm; line-height: 1.26; }
.glossario-item b { color: var(--navy); }

.fontes-lista { font-size: 7.6pt; line-height: 1.4; margin-bottom: 2.4mm; column-count: 2; column-gap: 6mm; }
.fontes-lista a { color: var(--navy); }
.fontes-lista .fonte-item { break-inside: avoid; margin-bottom: 0.3mm; }

.rodape-disclaimer {
  position: absolute; bottom: 14mm; left: 15mm; right: 15mm;
  font-size: 7.5pt; color: var(--cinza); border-top: 0.3mm solid var(--linha);
  padding-top: 1.4mm; text-align: center; line-height: 1.25;
}

.secao-vazia-nota { font-size: 7.6pt; color: var(--cinza); font-style: italic; }
"""


# --------------------------------------------------------------------------
# Página 1 — Capa
# --------------------------------------------------------------------------

def pagina1(ctx):
    edicao = ctx["edicao"]
    D = ctx["D"]
    cobertura = ctx["cobertura"]
    validos = cobertura.get("validos")
    total = cobertura.get("total")

    aviso = ""
    if edicao and D and edicao != D:
        aviso = (f'<div class="aviso-edicao">A edição de {esc(edicao)} analisa o pregão de {esc(D)}.</div>')

    conclusoes = ctx["conclusoes"][:3]
    li_conclusoes = "".join(f"<li>{esc(c)}</li>" for c in conclusoes)
    bloco_conclusoes = ""
    if li_conclusoes:
        bloco_conclusoes = f'<ul class="conclusoes">{li_conclusoes}</ul>'

    # Cartões macro
    macro = ctx["macro"]
    ordem_macro = [
        ("ibovespa", "Ibovespa", 2, None),
        ("usdbrl", "USD/BRL", 2, None),
        ("selic", "Selic", 2, "%"),
        ("ipca_12m", "IPCA 12m", 2, "%"),
        ("ipca_mes", "IPCA no mês", 2, "%"),
    ]
    cartoes_html = []
    for chave, titulo, casas, unidade in ordem_macro:
        item = macro.get(chave)
        if not isinstance(item, dict):
            item = {}
        valor = item.get("valor")
        rotulo = item.get("rotulo") or titulo
        data_obs = item.get("data")
        fonte = item.get("fonte")
        texto_val = fmt_numero(valor, casas) if unidade is None else fmt_numero(valor, casas)
        sufixo = f" {unidade}" if (unidade and valor is not None) else ""
        span_val = span_campo(f"macro.{chave}.valor", valor, texto_val + sufixo)
        delta_html = ""
        if chave == "ibovespa":
            dia_pct = item.get("dia_pct")
            texto_delta = fmt_var(dia_pct, 2, "%")
            cls = "pos" if (_num_valido(dia_pct) or 0) > 0 else ("neg" if (_num_valido(dia_pct) or 0) < 0 else "")
            delta_html = (f'<div class="delta {cls}">'
                          f'{span_campo("macro.ibovespa.dia_pct", dia_pct, texto_delta)}</div>')
        sub_partes = [esc(rotulo)]
        if data_obs:
            sub_partes.append(esc(data_obs))
        if fonte:
            sub_partes.append(esc(fonte))
        sub = " &middot; ".join(sub_partes)
        cartoes_html.append(
            f'<div class="cartao-macro"><div class="rot">{esc(titulo)}</div>'
            f'<div class="val">{span_val}</div>{delta_html}'
            f'<div class="sub">{sub}</div></div>'
        )
    bloco_macro = f'<div class="cartoes-macro">{"".join(cartoes_html)}</div>'

    # Amplitude
    amplitude = ctx["amplitude"]
    alta = amplitude.get("alta")
    amp_total = amplitude.get("total")
    amp_pct = amplitude.get("pct")
    txt_amp = f'{fmt_int(alta)} de {fmt_int(amp_total)} em alta'
    span_amp_num = span_campo("amplitude.alta", alta, fmt_int(alta))
    span_amp_total = span_campo("amplitude.total", amp_total, fmt_int(amp_total))
    span_amp_pct = span_campo("amplitude.pct", amp_pct, fmt_numero(amp_pct, 2) + " %")
    txt_amp_full = f'{span_amp_num} de {span_amp_total} em alta <span class="rot">({span_amp_pct})</span>'

    carteira = ctx["carteira"]
    ibov = ctx["ibov"]
    janelas = [("dia", "Dia"), ("d5", "5P"), ("d21", "21P")]
    itens_confronto = []
    for chave, rot in janelas:
        cv = get(carteira, chave, "valor")
        iv = ibov.get(chave)
        cls_c = "pos" if (_num_valido(cv) or 0) > 0 else ("neg" if (_num_valido(cv) or 0) < 0 else "")
        cls_i = "pos" if (_num_valido(iv) or 0) > 0 else ("neg" if (_num_valido(iv) or 0) < 0 else "")
        sp_c = span_campo(f"carteira.{chave}.valor", cv, fmt_var(cv, 2, "%"))
        sp_i = span_campo(f"ibov.{chave}", iv, fmt_var(iv, 2, "%"))
        itens_confronto.append(
            f'<div class="item"><div class="rot">{esc(rot)}</div>'
            f'<div class="linha">Cart. <b class="{cls_c}">{sp_c}</b> &nbsp;|&nbsp; '
            f'Ibov <b class="{cls_i}">{sp_i}</b></div></div>'
        )
    bloco_amplitude = (
        f'<div class="faixa-amplitude"><div class="num">{txt_amp_full}</div>'
        f'<div class="confronto-janelas">{"".join(itens_confronto)}</div></div>'
    )

    notas = ctx["notas"]
    bloco_notas = ""
    if notas:
        if len(notas) > 4:
            # Duas colunas para caber notas longas sem estourar a altura da página.
            meio = math.ceil(len(notas) / 2)
            col1 = "".join(f"<li>{esc(n)}</li>" for n in notas[:meio])
            col2 = "".join(f"<li>{esc(n)}</li>" for n in notas[meio:])
            corpo_notas = (f'<div class="notas-cols">'
                           f'<div class="col"><ul>{col1}</ul></div>'
                           f'<div class="col"><ul>{col2}</ul></div></div>')
        else:
            corpo_notas = f'<ul>{"".join(f"<li>{esc(n)}</li>" for n in notas)}</ul>'
        bloco_notas = (f'<div class="notas-edicao"><div class="secao-titulo">Notas desta edição</div>'
                       f'{corpo_notas}</div>')

    span_cobertura = (f'{span_campo("cobertura.validos", validos, fmt_int(validos))}/'
                      f'{span_campo("cobertura.total", total, fmt_int(total))}')

    return f'''
<section class="page">
  <div class="cabecalho">
    <h1>Carteira Brasil</h1>
    <div class="meta">Edição: <b>{esc(edicao) if edicao else "n/d"}</b> &middot; D: <b>{esc(D) if D else "n/d"}</b><br>
    Cobertura: <b>{span_cobertura}</b></div>
  </div>
  {aviso}
  {bloco_conclusoes}
  <div class="secao-titulo">Panorama macro</div>
  {bloco_macro}
  <div class="secao-titulo">Amplitude e carteira &times; Ibovespa</div>
  {bloco_amplitude}
  {bloco_notas}
</section>
'''


# --------------------------------------------------------------------------
# Página 2 — Panorama (heatmap, barras, comparativo)
# --------------------------------------------------------------------------

def _classe_pct(v):
    f = _num_valido(v)
    if f is None:
        return ""
    if f > 0:
        return "pos"
    if f < 0:
        return "neg"
    return ""


def _bloco_heatmap(ativos, paleta):
    colunas = [("dia", "Dia"), ("d5", "5P"), ("d21", "21P")]
    escalas = {}
    for chave, _ in colunas:
        vals = [abs(a.get(chave)) for a in ativos if _num_valido(a.get(chave)) is not None]
        escalas[chave] = max(vals) if vals else 1.0
        if escalas[chave] == 0:
            escalas[chave] = 1.0

    linhas = []
    for a in ativos:
        ticker = a.get("ticker") or "n/d"
        empresa = a.get("empresa") or ""
        celulas = []
        for chave, _ in colunas:
            v = a.get(chave)
            fv = _num_valido(v)
            campo = f"ativos.{ticker}.{chave}"
            if fv is None:
                celulas.append(
                    f'<td class="num">{span_campo(campo, v, "n/d", "celula-hm")}'
                    .replace('<span data-campo', '<span style="display:block;text-align:center;'
                             'background:#E8EAED;border-radius:0.8mm;padding:0.5mm 0;color:#5A6875;" data-campo')
                    + "</td>"
                )
            else:
                escala = escalas[chave]
                intensidade = min(abs(fv) / escala, 1.0) if escala else 0.0
                t = 0.14 + 0.86 * intensidade
                base = paleta["pos"] if fv >= 0 else paleta["neg"]
                fundo = mistura("#FFFFFF", base, t)
                cor_txt = texto_para_fundo(fundo, escuro="#1A2733", claro="#FFFFFF")
                texto = fmt_var(fv, 2, "%")
                estilo = f'display:block;text-align:center;background:{fundo};border-radius:0.8mm;padding:0.5mm 0;color:{cor_txt};font-weight:700;'
                celulas.append(
                    f'<td class="num"><span data-campo="{esc(campo)}" data-valor="{esc(valor_cru_str(v))}" '
                    f'style="{estilo}">{esc(texto)}</span></td>'
                )
        linhas.append(
            f'<tr><td class="ticker">{esc(ticker)} <span class="emp">{esc(empresa)}</span></td>{"".join(celulas)}</tr>'
        )

    cabecalho = "".join(f'<th class="num">{esc(rot)}</th>' for _, rot in colunas)
    tabela = (f'<table class="heatmap"><thead><tr><th>Ticker / Empresa</th>{cabecalho}</tr></thead>'
              f'<tbody>{"".join(linhas)}</tbody></table>')
    return (f'<div class="bloco"><div class="secao-titulo">Heatmap — Dia / 5P / 21P</div>'
            f'{tabela}</div>')


def _bloco_barras(ativos, ibov):
    validos = [a for a in ativos if _num_valido(a.get("d21")) is not None]
    if len(validos) < 12:
        return (f'<div class="bloco"><div class="secao-titulo">Ranking por 21P</div>'
                f'<div class="secao-vazia-nota">Gráfico omitido: apenas {len(validos)} de '
                f'{len(ativos)} ativos têm janela de 21P válida (mínimo de 12 exigido).</div></div>')

    ordenados = sorted(
        ativos,
        key=lambda a: (0, -a.get("d21")) if _num_valido(a.get("d21")) is not None else (1, 0),
    )
    escala = max([abs(a.get("d21")) for a in validos] + [0.01])
    ibov_d21 = ibov.get("d21")
    ibov_valido = _num_valido(ibov_d21) is not None
    if ibov_valido:
        escala = max(escala, abs(ibov_d21))
    escala = math.ceil(escala) if escala > 1 else round(escala + 0.5, 1)

    linhas = []
    for a in ordenados:
        ticker = a.get("ticker") or "n/d"
        empresa = a.get("empresa") or ""
        v = a.get("d21")
        fv = _num_valido(v)
        campo = f"ativos.{ticker}.d21"
        rot = f'<div class="rot"><b>{esc(ticker)}</b> <span class="emp">{esc(empresa)}</span></div>'
        if fv is None:
            linhas.append(
                f'<div class="barra-linha">{rot}<div class="barra-campo">'
                f'{span_campo(campo, v, "n/d", "barra-nd")}</div></div>'
            )
            continue
        pct_pos = 50.0 + (fv / escala) * 50.0
        pct_pos = max(1.0, min(99.0, pct_pos))
        esquerda = min(50.0, pct_pos)
        largura = abs(pct_pos - 50.0)
        cor = "var(--pos)" if fv >= 0 else "var(--neg)"
        texto_val = fmt_var(fv, 2, "%")
        perto_do_limite = largura > 40
        # Largura aproximada do rótulo em % da pista. Serve para garantir que
        # ele nunca caia sobre a linha tracejada do Ibovespa (§5.3): quando os
        # intervalos se cruzam, o rótulo é reposicionado para o outro lado.
        rot_w, folga = 14.0, 0.8
        pos_linha = None
        if ibov_valido:
            pos_linha = max(1.0, min(99.0, 50.0 + (ibov_d21 / escala) * 50.0))

        def _colide(ini):
            return (pos_linha is not None
                    and ini - folga < pos_linha < ini + rot_w + folga)

        # O rótulo só pode ficar FORA da barra se couber inteiro fora dela. Sem
        # esta checagem o clamp final (ini <= 100 - rot_w) puxa o rótulo de volta
        # para cima da barra mantendo a cor escura — texto escuro sobre barra
        # escura. Medido: BBDC3 +6,32%, 44% do rótulo sobre a barra.
        if fv >= 0:
            fim = esquerda + largura
            dentro = perto_do_limite or (fim + 0.4 + rot_w > 100.0)
            ini = (fim - rot_w - 0.4) if dentro else (fim + 0.4)
            if _colide(ini):
                depois = pos_linha + folga + 0.4
                ini = depois if depois + rot_w <= 99.0 else pos_linha - rot_w - folga - 0.4
                dentro = esquerda <= ini and ini + rot_w <= fim
        else:
            fim = esquerda
            dentro = perto_do_limite or (fim - 0.4 - rot_w < 0.0)
            ini = (fim + 0.4) if dentro else (fim - rot_w - 0.4)
            if _colide(ini):
                ini = pos_linha - rot_w - folga - 0.4
                dentro = False
        ini = max(0.0, min(ini, 100.0 - rot_w))
        pos_rot = f'left: {ini:.2f}%;'
        cor_rot = "#FFFFFF" if dentro else ("var(--navy)" if fv >= 0 else "var(--neg)")
        barra = (f'<div class="barra-valor" data-campo="{esc(campo)}" data-valor="{esc(valor_cru_str(v))}" '
                 f'style="left:{esquerda}%;width:{largura}%;background:{cor};"></div>')
        rotulo = (f'<span class="barra-rotulo ok-overlap" style="{pos_rot}color:{cor_rot};">{esc(texto_val)}</span>')
        ibov_marca = ""
        linhas.append(
            f'<div class="barra-linha">{rot}<div class="barra-campo">'
            f'<div class="barra-zero"></div>{barra}{rotulo}</div></div>'
        )

    marca_ibov = ""
    if ibov_valido:
        pos_ibov = 50.0 + (ibov_d21 / escala) * 50.0
        pos_ibov = max(1.0, min(99.0, pos_ibov))
        marca_ibov = (
            f'<div class="barra-ibov ok-overlap" data-campo="ibov.d21" data-valor="{esc(valor_cru_str(ibov_d21))}" '
            f'style="left:calc(42mm + (100% - 42mm) * {pos_ibov / 100:.4f});"></div>'
        )

    legenda_escala = (f'<div class="barras-legenda"><span>escala: {MENOS}{fmt_numero(escala,1)} % a '
                      f'+{fmt_numero(escala,1)} %</span>'
                      f'<span>{"linha tracejada = Ibov 21P (" + fmt_var(ibov_d21,2,"%") + ")" if ibov_valido else "Ibov 21P indisponível"}</span></div>')

    return (f'<div class="bloco"><div class="secao-titulo">Ranking por 21P (maior para menor)</div>'
            f'<div class="barras-wrap">{legenda_escala}{"".join(linhas)}{marca_ibov}</div></div>')


def _bloco_comparativo(carteira, ibov):
    janelas = [("d5", "5P"), ("d21", "21P")]
    paineis = []
    for chave, rot in janelas:
        n = get(carteira, chave, "n")
        cv = get(carteira, chave, "valor")
        iv = ibov.get(chave)
        if n is not None and _num_valido(n) is not None and n < 12:
            paineis.append(
                f'<div class="painel-comp"><div class="titulo">Carteira &times; Ibovespa — {esc(rot)}</div>'
                f'<div class="comp-nd">Painel omitido: apenas {fmt_int(n)} ativos com janela {esc(rot)} '
                f'válida (mínimo de 12 exigido).</div></div>'
            )
            continue
        vals = [x for x in (_num_valido(cv), _num_valido(iv)) if x is not None]
        escala = max([abs(x) for x in vals] + [1.0])
        escala = round(escala * 1.15, 1) if escala else 1.0

        def barra_h(rotulo_item, valor, campo):
            fv = _num_valido(valor)
            if fv is None:
                return (f'<div class="comp-barra-linha"><div class="rot">{esc(rotulo_item)}</div>'
                        f'<div class="barra-campo">{span_campo(campo, valor, "n/d", "barra-nd")}</div></div>')
            pct_pos = 50.0 + (fv / escala) * 50.0 if escala else 50.0
            pct_pos = max(1.0, min(99.0, pct_pos))
            esquerda = min(50.0, pct_pos)
            largura = abs(pct_pos - 50.0)
            cor = "var(--pos)" if fv >= 0 else "var(--neg)"
            texto_val = fmt_var(fv, 2, "%")
            # Largura aproximada do rótulo em % da pista: ~42px de uma pista de
            # 243px a 6,8pt. O limiar de barra larga sozinho não basta — uma
            # barra logo ABAIXO dele empurra o rótulo para fora e ele transborda
            # a pista. Medido: Ibovespa 21P, barra de 36,8% (portanto "estreita"),
            # rótulo terminando 14px além da borda direita da pista.
            # Regra: o rótulo só vai para fora se comprovadamente couber lá.
            rot_w = 18.0
            if fv >= 0:
                cabe_fora = (esquerda + largura) + rot_w <= 100.0
            else:
                cabe_fora = esquerda - rot_w >= 0.0
            if largura > 38 or not cabe_fora:
                cor_rot = "#FFFFFF"
                pos_rot = f'left: calc({esquerda}% + 0.8mm);'
            else:
                cor_rot = "var(--navy)" if fv >= 0 else "var(--neg)"
                if fv >= 0:
                    pos_rot = f'left: calc({esquerda + largura}% + 1mm);'
                else:
                    pos_rot = f'right: calc({100 - esquerda}% + 1mm);'
            barra = (f'<div class="barra-valor" data-campo="{esc(campo)}" data-valor="{esc(valor_cru_str(valor))}" '
                     f'style="left:{esquerda}%;width:{largura}%;background:{cor};"></div>')
            rotulo = f'<span class="barra-rotulo ok-overlap" style="{pos_rot}color:{cor_rot};">{esc(texto_val)}</span>'
            return (f'<div class="comp-barra-linha"><div class="rot">{esc(rotulo_item)}</div>'
                    f'<div class="barra-campo"><div class="barra-zero"></div>{barra}{rotulo}</div></div>')

        corpo = (barra_h("Carteira", cv, f"carteira.{chave}.valor")
                 + barra_h("Ibovespa", iv, f"ibov.{chave}"))
        paineis.append(
            f'<div class="painel-comp"><div class="titulo">Carteira &times; Ibovespa — {esc(rot)}</div>'
            f'<div class="escala">escala: {MENOS}{fmt_numero(escala,1)} % a +{fmt_numero(escala,1)} %</div>'
            f'{corpo}</div>'
        )
    return (f'<div class="bloco"><div class="secao-titulo">Carteira &times; Ibovespa — 5P e 21P</div>'
            f'<div class="comparativo">{"".join(paineis)}</div></div>')


def pagina2(ctx):
    ativos = ctx["ativos"]
    ibov = ctx["ibov"]
    carteira = ctx["carteira"]
    return f'''
<section class="page">
  <div class="cabecalho"><h1 style="font-size:13pt;">Panorama</h1>
    <div class="meta">D: <b>{esc(ctx["D"]) if ctx["D"] else "n/d"}</b></div></div>
  {_bloco_heatmap(ativos, ctx["paleta"])}
  {_bloco_barras(ativos, ibov)}
  {_bloco_comparativo(carteira, ibov)}
</section>
'''


# --------------------------------------------------------------------------
# Página 3 — Destaques
# --------------------------------------------------------------------------

def pagina3(ctx):
    destaques = ctx["destaques"][:5]
    cards = []
    for d in destaques:
        ticker = d.get("ticker") or "n/d"
        empresa = d.get("empresa") or ""
        leitura = d.get("leitura") or "SEM DADOS"
        slug = slug_leitura(leitura)
        fonte = d.get("fonte") or {}
        veiculo = fonte.get("veiculo")
        data_f = fonte.get("data")
        url_f = fonte.get("url")
        fonte_html = ""
        if veiculo or url_f:
            rotulo_fonte = esc(veiculo) if veiculo else "fonte"
            if data_f:
                rotulo_fonte += f' &middot; {esc(data_f)}'
            if url_f:
                fonte_html = f'<div class="fonte">Fonte: <a href="{esc(url_f)}">{rotulo_fonte}</a></div>'
            else:
                fonte_html = f'<div class="fonte">Fonte: {rotulo_fonte}</div>'
        cards.append(
            f'<div class="card-destaque"><div class="topo">'
            f'<div class="titulo">{esc(ticker)} &middot; {esc(empresa)}</div>'
            f'<span class="pilula {slug}">{esc(leitura)}</span></div>'
            f'<div class="corpo">'
            f'<p><b>Fato:</b> {esc(d.get("fato"))}</p>'
            f'<p><b>Impacto:</b> {esc(d.get("impacto"))}</p>'
            f'<p><b>Risco/contraponto:</b> {esc(d.get("risco"))}</p>'
            f'</div>{fonte_html}</div>'
        )
    bloco_cards = f'<div class="cards-destaque">{"".join(cards)}</div>' if cards else ""

    complemento_html = ""
    if len(destaques) < 3:
        comp = ctx["destaques_complemento"]
        if isinstance(comp, dict) and comp.get("linhas"):
            titulo_c = comp.get("titulo") or "Complemento"
            linhas_lista = comp.get("linhas") or []
            if len(linhas_lista) > 4:
                # Duas colunas para caber o complemento sem estourar a página.
                meio = math.ceil(len(linhas_lista) / 2)
                col1 = "".join(f"<li>{esc(l)}</li>" for l in linhas_lista[:meio])
                col2 = "".join(f"<li>{esc(l)}</li>" for l in linhas_lista[meio:])
                corpo_comp = (f'<div class="comp-cols">'
                              f'<div class="col"><ul>{col1}</ul></div>'
                              f'<div class="col"><ul>{col2}</ul></div></div>')
            else:
                corpo_comp = f'<ul>{"".join(f"<li>{esc(l)}</li>" for l in linhas_lista)}</ul>'
            complemento_html = (f'<div class="complemento"><div class="titulo">{esc(titulo_c)}</div>'
                               f'{corpo_comp}</div>')

    if not cards and not complemento_html:
        conteudo = '<div class="secao-vazia-nota">Nenhum destaque editorial disponível nesta edição.</div>'
    else:
        conteudo = bloco_cards + complemento_html

    return f'''
<section class="page">
  <div class="cabecalho"><h1 style="font-size:13pt;">Destaques</h1></div>
  {conteudo}
</section>
'''


# --------------------------------------------------------------------------
# Página 4 — Quadro completo
# --------------------------------------------------------------------------

def pagina4(ctx):
    ativos = ctx["ativos"]
    linhas = []
    for a in ativos:
        ticker = a.get("ticker") or "n/d"
        empresa = a.get("empresa") or ""
        cotacao = a.get("cotacao")
        ref = a.get("ref") or ""
        dia = a.get("dia")
        d5 = a.get("d5")
        d21 = a.get("d21")
        leitura = a.get("leitura") or "SEM DADOS"
        slug = slug_leitura(leitura)
        contexto = a.get("contexto") or ""

        sp_cot = span_campo(f"ativos.{ticker}.cotacao", cotacao, fmt_numero(cotacao, 2))
        sp_dia = span_campo(f"ativos.{ticker}.dia", dia, fmt_var(dia, 2, "%"))
        sp_d5 = span_campo(f"ativos.{ticker}.d5", d5, fmt_var(d5, 2, "%"))
        sp_d21 = span_campo(f"ativos.{ticker}.d21", d21, fmt_var(d21, 2, "%"))
        cls_dia = _classe_pct(dia)
        cls_d5 = _classe_pct(d5)
        cls_d21 = _classe_pct(d21)

        linhas.append(
            f'<tr><td class="ticker"><b>{esc(ticker)}</b></td><td>{esc(empresa)}</td>'
            f'<td class="num">{sp_cot}</td><td class="ref">{esc(ref)}</td>'
            f'<td class="num {cls_dia}">{sp_dia}</td>'
            f'<td class="num {cls_d5}">{sp_d5}</td>'
            f'<td class="num {cls_d21}">{sp_d21}</td>'
            f'<td><span class="pilula {slug}">{esc(leitura)}</span></td>'
            f'<td class="contexto">{esc(contexto)}</td></tr>'
        )

    # Larguras medidas no Chromium a 7,4pt (célula) e 6,9pt (cabeçalho), com
    # 1,1mm de padding de cada lado. Pior caso de cada coluna:
    #   Ticker   "BRBI11" nowrap ....................  13,2mm -> 15mm
    #   Empresa  quebra em 2 linhas .................. livre  -> 19mm
    #   Cotação  cabeçalho "Cotação" (6,9pt) ......... 13,7mm -> 14mm
    #   Ref.     "fechamento D" nowrap ............... 20,7mm -> 21mm
    #   Dia/5P/21P  "−12,38 %" (duas casas inteiras) . 15,2mm -> 15,2mm
    #   Leitura  pílula "FAVORÁVEL" ................... 18,4mm -> 19mm
    # Não estreite nenhuma delas: com |21P| >= 10% o valor transbordava a
    # célula e o "%" ia parar debaixo da pílula de Leitura (6 sobreposições).
    tabela = ('<table class="quadro"><colgroup>'
              '<col style="width:15mm"><col style="width:19mm"><col style="width:14mm">'
              '<col style="width:21mm"><col style="width:15.2mm"><col style="width:15.2mm">'
              '<col style="width:15.2mm"><col style="width:19mm"><col>'
              '</colgroup><thead><tr>'
              '<th>Ticker</th><th>Empresa</th><th>Cotação</th><th>Ref.</th>'
              '<th>Dia</th><th>5P</th><th>21P</th><th>Leitura</th><th>Contexto</th>'
              f'</tr></thead><tbody>{"".join(linhas)}</tbody></table>')

    return f'''
<section class="page">
  <div class="cabecalho"><h1 style="font-size:13pt;">Quadro completo</h1>
    <div class="meta">{len(ativos)} ativos</div></div>
  {tabela}
</section>
'''


# --------------------------------------------------------------------------
# Página 5 — Agenda, legenda, metodologia, glossário, fontes
# --------------------------------------------------------------------------

def pagina5(ctx):
    agenda = ctx["agenda"]
    bloco_agenda = ""
    if agenda:
        linhas = "".join(
            f'<tr><td>{esc(ev.get("data"))}</td><td>{esc(ev.get("evento"))}</td>'
            f'<td>{esc(ev.get("fonte"))}</td></tr>'
            for ev in agenda
        )
        bloco_agenda = (f'<div class="secao-titulo">Agenda</div>'
                        f'<table class="agenda"><thead><tr><th>Data</th><th>Evento</th><th>Fonte</th></tr></thead>'
                        f'<tbody>{linhas}</tbody></table>')
    else:
        bloco_agenda = ('<div class="secao-titulo">Agenda</div>'
                        '<div class="secao-vazia-nota" style="margin-bottom:2.4mm;">'
                        'Nenhum evento de agenda cadastrado nesta edição.</div>')

    agenda_nota = ctx.get("agenda_nota")
    bloco_agenda_nota = f'<div class="agenda-nota">{esc(agenda_nota)}</div>' if agenda_nota else ""

    legenda = ctx["legenda"]
    bloco_legenda = ""
    if legenda:
        itens = []
        for it in legenda:
            leitura = it.get("leitura") or ""
            slug = slug_leitura(leitura)
            itens.append(
                f'<div class="legenda-item"><span class="pilula {slug}">{esc(leitura)}</span>'
                f'<span>{esc(it.get("texto"))}</span></div>'
            )
        bloco_legenda = (f'<div class="secao-titulo">Legenda das leituras</div>'
                         f'<div class="legenda-lista">{"".join(itens)}</div>')

    metodologia = ctx["metodologia"][:8]
    bloco_metodologia = ""
    if metodologia:
        itens = "".join(f"<li>{esc(m)}</li>" for m in metodologia)
        bloco_metodologia = (f'<div class="secao-titulo">Metodologia</div>'
                             f'<ul class="metodologia-lista">{itens}</ul>')

    glossario = ctx["glossario"]
    bloco_glossario = ""
    if glossario:
        meio = math.ceil(len(glossario) / 2)
        col1 = glossario[:meio]
        col2 = glossario[meio:]

        def render_col(itens):
            return "".join(f'<div class="glossario-item"><b>{esc(it.get("termo"))}:</b> {esc(it.get("texto"))}</div>'
                          for it in itens)

        bloco_glossario = (f'<div class="secao-titulo">Glossário</div>'
                           f'<div class="glossario-cols"><div class="col">{render_col(col1)}</div>'
                           f'<div class="col">{render_col(col2)}</div></div>')

    fontes = ctx["fontes"]
    bloco_fontes = ""
    if fontes:
        itens = "".join(
            '<div class="fonte-item">'
            + (f'<a href="{esc(f.get("url"))}">{esc(f.get("titulo"))}</a>' if f.get("url") else esc(f.get("titulo")))
            + '</div>'
            for f in fontes
        )
        bloco_fontes = (f'<div class="secao-titulo">Fontes</div><div class="fontes-lista">{itens}</div>')

    rodape = ctx.get("rodape") or (
        "Este material é análise editorial informativa, não recomendação de investimento personalizada."
    )

    return f'''
<section class="page">
  <div class="cabecalho"><h1 style="font-size:13pt;">Agenda, legenda e metodologia</h1></div>
  {bloco_agenda}
  {bloco_agenda_nota}
  {bloco_legenda}
  {bloco_metodologia}
  {bloco_glossario}
  {bloco_fontes}
  <div class="rodape-disclaimer">{esc(rodape)}</div>
</section>
'''


# --------------------------------------------------------------------------
# Script de medição do checador (injetado no HTML)
# --------------------------------------------------------------------------

SCRIPT_CHECADOR = r"""
<script>
(function() {
  function rectOf(el) {
    var r = el.getBoundingClientRect();
    return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height};
  }
  function intersecta(a, b) {
    var ix = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    var iy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return ix > 4 && iy > 4;
  }
  function ehAncestral(a, b) {
    return a.contains(b) || b.contains(a);
  }
  var paginas = Array.prototype.slice.call(document.querySelectorAll('.page'));
  var resultadoPaginas = [];
  paginas.forEach(function(pagina, idx) {
    var n = idx + 1;
    var pageRect = pagina.getBoundingClientRect();
    var estiloPagina = window.getComputedStyle(pagina);
    var padTop = parseFloat(estiloPagina.paddingTop) || 0;
    var padBottom = parseFloat(estiloPagina.paddingBottom) || 0;
    // Área útil = altura da página menos os paddings (não a altura cheia do
    // elemento .page, que inclui a faixa de padding onde não deveria haver
    // conteúdo visível).
    var alturaUtil = Math.max(0, pageRect.height - padTop - padBottom);
    var limiteInferior = pageRect.bottom - padBottom;
    var elementos = Array.prototype.slice.call(pagina.querySelectorAll('*')).filter(function(el) {
      var r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return false;
      if (el.children.length > 0) {
        var temTextoDireto = false;
        for (var i = 0; i < el.childNodes.length; i++) {
          var nd = el.childNodes[i];
          if (nd.nodeType === 3 && nd.textContent.trim().length > 0) { temTextoDireto = true; break; }
        }
        if (!temTextoDireto) return false;
      }
      return true;
    });
    var menorTop = Infinity, maiorBottom = -Infinity;
    elementos.forEach(function(el) {
      var r = rectOf(el);
      if (r.top < menorTop) menorTop = r.top;
      if (r.bottom > maiorBottom) maiorBottom = r.bottom;
    });
    var alturaOcupada = (menorTop === Infinity) ? 0 : Math.max(0, maiorBottom - Math.max(menorTop, pageRect.top));

    // Corte de conteúdo: qualquer elemento cujo bottom ultrapasse o limite
    // inferior da área útil em mais de 2px está sendo decepado pelo
    // overflow:hidden da página (o defeito mais grave desta rotina).
    var cortes = [];
    elementos.forEach(function(el) {
      var r = rectOf(el);
      var excedeu = r.bottom - limiteInferior;
      if (excedeu > 2) {
        var classes = (el.className && typeof el.className === 'string') ? el.className.trim() : '';
        var seletor = el.tagName.toLowerCase() + (classes ? '.' + classes.replace(/\s+/g, '.') : '');
        cortes.push({
          seletor: seletor,
          texto: (el.textContent || '').trim().slice(0, 60),
          excedeu_px: Math.round(excedeu * 100) / 100
        });
      }
    });
    cortes.sort(function(a, b) { return b.excedeu_px - a.excedeu_px; });
    cortes = cortes.slice(0, 30);

    var sobreposicoes = [];
    var candidatos = Array.prototype.slice.call(pagina.querySelectorAll(
      'p, span, div.cartao-macro, td, th, li, a, .barra-rotulo, .barra-valor, .celula-hm, .pilula'
    )).filter(function(el) {
      if (el.classList.contains('ok-overlap')) return false;
      var r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    });
    for (var i = 0; i < candidatos.length && sobreposicoes.length < 20; i++) {
      for (var j = i + 1; j < candidatos.length && sobreposicoes.length < 20; j++) {
        var A = candidatos[i], B = candidatos[j];
        if (A.classList.contains('ok-overlap') || B.classList.contains('ok-overlap')) continue;
        if (ehAncestral(A, B)) continue;
        var ra = rectOf(A), rb = rectOf(B);
        if (intersecta(ra, rb)) {
          sobreposicoes.push({a: A.tagName + '.' + (A.className || ''), b: B.tagName + '.' + (B.className || '')});
        }
      }
    }

    var transbordos = [];
    Array.prototype.slice.call(pagina.querySelectorAll('*')).forEach(function(el) {
      if (el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2) {
        var estilo = window.getComputedStyle(el);
        if (estilo.overflow === 'auto' || estilo.overflow === 'scroll' || estilo.overflowX === 'auto' || estilo.overflowY === 'auto') return;
        transbordos.push(el.tagName + '.' + (el.className || ''));
      }
    });

    var vazioPct = alturaUtil > 0 ? (1 - (alturaOcupada / alturaUtil)) * 100 : 0;
    var motivos = [];
    if (cortes.length > 0) motivos.push('corte');
    if (sobreposicoes.length > 0) motivos.push('sobreposicao');
    if (transbordos.length > 0) motivos.push('transbordo');
    // A capa (P1) e um frontispicio: titulo, conclusoes, cartoes macro,
    // amplitude e notas ocupam legitimamente cerca de metade de uma A4.
    // Exigir 65% de ocupacao dela so premiaria tipografia inflada. As
    // paginas de conteudo seguem em 35%.
    var limiteVazio = (n === 1) ? 48 : 35;
    if (vazioPct > limiteVazio) motivos.push('vazio>' + limiteVazio + '%');
    resultadoPaginas.push({
      n: n,
      altura_util_px: Math.round(alturaUtil * 100) / 100,
      altura_ocupada_px: Math.round(alturaOcupada * 100) / 100,
      vazio_pct: Math.round(vazioPct * 100) / 100,
      sobreposicoes: sobreposicoes,
      transbordos: transbordos,
      cortes: cortes,
      reprovada: motivos.length > 0,
      motivos: motivos
    });
  });

  var campos = [];
  Array.prototype.slice.call(document.querySelectorAll('[data-campo]')).forEach(function(el) {
    campos.push({
      campo: el.getAttribute('data-campo'),
      valor_cru: el.getAttribute('data-valor'),
      texto_render: el.textContent
    });
  });

  var reprovado = resultadoPaginas.some(function(p) { return p.reprovada; });
  var motivosGlobais = resultadoPaginas.filter(function(p) { return p.reprovada; })
    .map(function(p) { return 'P' + p.n + ': ' + p.motivos.join(','); });
  var resumo = reprovado ? (motivosGlobais.length + ' página(s) reprovada(s): ' + motivosGlobais.join('; ')) : 'nenhuma página reprovada';

  var relatorio = {
    paginas: resultadoPaginas,
    campos: campos,
    reprovado: reprovado,
    resumo: resumo
  };

  var pre = document.createElement('pre');
  pre.id = '__checador__';
  pre.style.display = 'none';
  pre.textContent = JSON.stringify(relatorio);
  document.body.appendChild(pre);
})();
</script>
"""


# --------------------------------------------------------------------------
# Montagem do HTML completo
# --------------------------------------------------------------------------

def montar_html(ctx, incluir_checador):
    paginas = [pagina1(ctx), pagina2(ctx), pagina3(ctx), pagina4(ctx), pagina5(ctx)]
    corpo = "\n".join(paginas)
    script = SCRIPT_CHECADOR if incluir_checador else ""
    titulo = ctx.get("titulo_edicao") or "Carteira Brasil"
    css = css_paleta(ctx["paleta"]) + "\n" + CSS_BASE
    return f'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>{esc(titulo)}</title>
<style>{css}</style>
</head>
<body>
{corpo}
{script}
</body>
</html>
'''


# --------------------------------------------------------------------------
# Execução do Chromium
# --------------------------------------------------------------------------

def rodar_print_to_pdf(chrome, html_path, pdf_path):
    cmd = [
        chrome, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
        f"--print-to-pdf={pdf_path}", "--print-to-pdf-no-header",
        "--virtual-time-budget=10000", f"file://{html_path}",
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)


def rodar_dump_dom(chrome, html_path, dump_path):
    cmd = [
        chrome, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
        "--dump-dom", "--virtual-time-budget=8000", f"file://{html_path}",
    ]
    with open(dump_path, "wb") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.DEVNULL, timeout=90)


def extrair_checador(dump_path):
    with open(dump_path, "r", encoding="utf-8", errors="replace") as f:
        conteudo = f.read()
    marca_ini = '<pre id="__checador__"'
    i = conteudo.find(marca_ini)
    if i == -1:
        return None
    j = conteudo.find(">", i)
    if j == -1:
        return None
    k = conteudo.find("</pre>", j)
    if k == -1:
        return None
    bruto = conteudo[j + 1:k]
    texto = html.unescape(bruto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    if len(sys.argv) != 5:
        sys.stderr.write("uso: gerador_pdf.py <dataset.json> <editorial.json> <saida.pdf> <relatorio_checador.json>\n")
        sys.exit(2)

    caminho_dataset, caminho_editorial, caminho_pdf, caminho_relatorio = sys.argv[1:5]

    dataset = carregar_json(caminho_dataset)
    editorial = carregar_json(caminho_editorial)
    ctx = montar_contexto(dataset, editorial)

    chrome = localizar_chromium()

    with tempfile.TemporaryDirectory(prefix="cb_pdf_") as tmpdir:
        html_path = os.path.join(tmpdir, "carteira.html")
        dump_path = os.path.join(tmpdir, "dump.html")

        html_final = montar_html(ctx, incluir_checador=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_final)

        pdf_abs = os.path.abspath(caminho_pdf)
        rodar_print_to_pdf(chrome, html_path, pdf_abs)
        rodar_dump_dom(chrome, html_path, dump_path)
        relatorio = extrair_checador(dump_path)

    if relatorio is None:
        relatorio = {
            "paginas": [],
            "campos": [],
            "reprovado": True,
            "resumo": "falha ao extrair relatório do checador (dump-dom não retornou dados)",
        }

    with open(caminho_relatorio, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    linhas_saida = []
    for p in relatorio.get("paginas", []):
        veredito = "REPROVADA" if p.get("reprovada") else "ok"
        linhas_saida.append(
            f'P{p.get("n")}: vazio={p.get("vazio_pct")}% cortes={len(p.get("cortes", []))} '
            f'sobrep={len(p.get("sobreposicoes", []))} transb={len(p.get("transbordos", []))} -> {veredito}'
        )
    linhas_saida.append(f'campos coletados: {len(relatorio.get("campos", []))}')
    linhas_saida.append(f'veredito global: {"REPROVADO" if relatorio.get("reprovado") else "APROVADO"} - {relatorio.get("resumo")}')

    print(f"PDF gerado em: {caminho_pdf}")
    for linha in linhas_saida[:14]:
        print(linha)


if __name__ == "__main__":
    main()
