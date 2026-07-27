# GERADOR CARTEIRA BRASIL
"""
gerador_painel.py — monta o painel HTML interativo "Carteira Brasil" a
partir de dataset.json e editorial.json.

Uso:
    python3 gerador_painel.py <dataset.json> <editorial.json> <saida.html>

Só usa stdlib (json, sys, os, html). Sem rede, sem lib externa. A saída é
um fragmento autocontido — sem <!doctype>, <html>, <head> ou <body> — para
ser publicado como Artifact (que já fornece esse invólucro).
"""

import sys
import json
import html


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def carregar_json(caminho):
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def escapa_para_script(texto_json):
    # evita que um "</script" dentro de uma string de dados feche a tag
    # <script> prematuramente.
    return texto_json.replace("</", "<\\/")


# --------------------------------------------------------------------------
# Paleta — validada para visão de cores; lida de dataset["paleta"] quando
# presente, com fallback para os hexes validados abaixo. Independente do
# gerador_pdf.py (cada gerador é um programa autônomo, sem import cruzado).
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
    bruta = dataset.get("paleta") if isinstance(dataset, dict) else None
    paleta = dict(PALETA_FALLBACK)
    if isinstance(bruta, dict):
        for chave in PALETA_FALLBACK:
            v = bruta.get(chave)
            if _hex_valido(v):
                paleta[chave] = v.strip()
    return paleta


def _hex_para_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _luminancia_relativa(hexcor):
    r, g, b = _hex_para_rgb(hexcor)

    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _razao_contraste(h1, h2):
    l1 = _luminancia_relativa(h1)
    l2 = _luminancia_relativa(h2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def texto_para_fundo(fundo_hex, escuro="#1A2733", claro="#FFFFFF"):
    if _razao_contraste(fundo_hex, escuro) >= _razao_contraste(fundo_hex, claro):
        return escuro
    return claro


def css_paleta(paleta):
    """Bloco :root/tema com a paleta de dados (lida de dataset['paleta'],
    com fallback para os hexes validados). As cores de texto das pílulas
    (--txt-*) são sempre calculadas pela função de contraste — nunca
    fixas — porque --semd é clara e precisa de texto escuro, ao contrário
    de --fav/--aten/--neut."""
    # Paleta escura (tema dark) mantém os tons já ajustados para fundo
    # escuro; não vem do dataset (que só define a paleta de impressão/tema
    # claro), mas sua cor de texto também é recalculada, nunca fixa.
    paleta_dark = {
        "pos": "#35B79B", "neg": "#E17167", "fav": "#35B79B",
        "aten": "#E0954C", "neut": "#9AA7B4", "semd": "#B39DDB",
    }

    def txts(p):
        return {
            "fav": texto_para_fundo(p["fav"]),
            "aten": texto_para_fundo(p["aten"]),
            "neut": texto_para_fundo(p["neut"]),
            "semd": texto_para_fundo(p["semd"]),
        }

    tl = txts(paleta)
    td = txts(paleta_dark)

    return f"""/* ==== PALETA ==== */
:root {{
  --navy:   #0B2340;
  --gold:   #C9A227;
  --fundo:  #FFFFFF;
  --texto:  #1A2733;
  --cinza:  #5A6875;
  --linha:  #D8DEE5;
  --painel: #FAFBFC;

  --pos:  {paleta['pos']};
  --neg:  {paleta['neg']};
  --fav:  {paleta['fav']};
  --aten: {paleta['aten']};
  --neut: {paleta['neut']};
  --semd: {paleta['semd']};

  --txt-fav:  {tl['fav']};
  --txt-aten: {tl['aten']};
  --txt-neut: {tl['neut']};
  --txt-semd: {tl['semd']};
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --navy:   #DCE6F2;
    --gold:   #E0C062;
    --fundo:  #10161F;
    --texto:  #E7ECF2;
    --cinza:  #9AA7B4;
    --linha:  #2B3947;
    --painel: #182230;

    --pos:  {paleta_dark['pos']};
    --neg:  {paleta_dark['neg']};
    --fav:  {paleta_dark['fav']};
    --aten: {paleta_dark['aten']};
    --neut: {paleta_dark['neut']};
    --semd: {paleta_dark['semd']};

    --txt-fav:  {td['fav']};
    --txt-aten: {td['aten']};
    --txt-neut: {td['neut']};
    --txt-semd: {td['semd']};
  }}
}}
:root[data-theme="dark"] {{
  --navy:   #DCE6F2;
  --gold:   #E0C062;
  --fundo:  #10161F;
  --texto:  #E7ECF2;
  --cinza:  #9AA7B4;
  --linha:  #2B3947;
  --painel: #182230;

  --pos:  {paleta_dark['pos']};
  --neg:  {paleta_dark['neg']};
  --fav:  {paleta_dark['fav']};
  --aten: {paleta_dark['aten']};
  --neut: {paleta_dark['neut']};
  --semd: {paleta_dark['semd']};

  --txt-fav:  {td['fav']};
  --txt-aten: {td['aten']};
  --txt-neut: {td['neut']};
  --txt-semd: {td['semd']};
}}
:root[data-theme="light"] {{
  --navy:   #0B2340;
  --gold:   #C9A227;
  --fundo:  #FFFFFF;
  --texto:  #1A2733;
  --cinza:  #5A6875;
  --linha:  #D8DEE5;
  --painel: #FAFBFC;

  --pos:  {paleta['pos']};
  --neg:  {paleta['neg']};
  --fav:  {paleta['fav']};
  --aten: {paleta['aten']};
  --neut: {paleta['neut']};
  --semd: {paleta['semd']};

  --txt-fav:  {tl['fav']};
  --txt-aten: {tl['aten']};
  --txt-neut: {tl['neut']};
  --txt-semd: {tl['semd']};
}}
/* ==== FIM PALETA ==== */"""


CSS_BASE = """
* { box-sizing: border-box; }

.cb-raiz {
  font-family: 'DejaVu Sans', 'Noto Sans', sans-serif;
  color: var(--texto);
  background: var(--fundo);
  max-width: 62rem;
  margin: 0 auto;
  padding: 1.2rem 1rem 3rem;
  line-height: 1.4;
}

.cb-cabecalho {
  display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end;
  gap: 0.8rem; border-bottom: 0.2rem solid var(--gold); padding-bottom: 0.6rem; margin-bottom: 1rem;
}
.cb-cabecalho h1 { font-size: 1.5rem; color: var(--navy); margin: 0; }
.cb-cabecalho .cb-meta { font-size: 0.85rem; color: var(--cinza); text-align: right; }
.cb-cabecalho .cb-meta b { color: var(--navy); }

.cb-botao-tema {
  background: var(--painel); color: var(--texto); border: 0.06rem solid var(--linha);
  border-radius: 0.4rem; padding: 0.35rem 0.7rem; font-size: 0.85rem; cursor: pointer;
}
.cb-botao-tema:hover { border-color: var(--gold); }

.cb-secao { margin-bottom: 1.6rem; }
.cb-secao h2 {
  font-size: 1rem; color: var(--navy); text-transform: uppercase; letter-spacing: 0.03rem;
  border-bottom: 0.06rem solid var(--linha); padding-bottom: 0.3rem; margin-bottom: 0.7rem;
}

.cb-resumo-carteira { display: flex; gap: 1rem; flex-wrap: wrap; }
.cb-resumo-item { background: var(--painel); border: 0.06rem solid var(--linha); border-radius: 0.5rem; padding: 0.6rem 0.9rem; min-width: 8rem; }
.cb-resumo-item .rot { font-size: 0.75rem; color: var(--cinza); text-transform: uppercase; }
.cb-resumo-item .linha { font-size: 0.95rem; margin-top: 0.2rem; }

.cb-pos { color: var(--pos); }
.cb-neg { color: var(--neg); }

.cb-scroll-x { overflow-x: auto; max-width: 100%; }

table.cb-tabela { border-collapse: collapse; width: 100%; font-size: 0.85rem; min-width: 30rem; }
table.cb-tabela th, table.cb-tabela td { padding: 0.35rem 0.5rem; border-bottom: 0.06rem solid var(--linha); text-align: left; }
table.cb-tabela th { color: var(--cinza); font-weight: 700; font-size: 0.78rem; text-transform: uppercase; white-space: nowrap; }
table.cb-tabela td.num, table.cb-tabela th.num { text-align: right; }

th.cb-ordenavel { cursor: pointer; user-select: none; }
th.cb-ordenavel:hover { color: var(--navy); }
th.cb-ordenavel .cb-seta { font-size: 0.7rem; margin-left: 0.15rem; color: var(--gold); }

.cb-celula-hm { display: block; text-align: center; border-radius: 0.25rem; padding: 0.15rem 0.3rem; font-weight: 700; cursor: default; min-width: 3.4rem; }

.cb-pilula { display: inline-block; padding: 0.08rem 0.5rem; border-radius: 0.7rem; font-size: 0.72rem; font-weight: 700; white-space: nowrap; }
.cb-pilula.favoravel { background: var(--fav);  color: var(--txt-fav); }
.cb-pilula.atencao   { background: var(--aten); color: var(--txt-aten); }
.cb-pilula.neutro    { background: var(--neut); color: var(--txt-neut); }
.cb-pilula.sem-dados { background: var(--semd); color: var(--txt-semd); }

.cb-pilula-contorno { display: inline-block; padding: 0.08rem 0.5rem; border-radius: 0.7rem; font-size: 0.72rem; font-weight: 700; border: 0.1rem solid var(--texto); color: var(--texto); }

.cb-tooltip {
  position: fixed; display: none; background: var(--navy); color: #fff; font-size: 0.78rem;
  padding: 0.35rem 0.55rem; border-radius: 0.35rem; pointer-events: none; z-index: 50; max-width: 16rem;
}

.cb-botoes-janela { display: flex; gap: 0.5rem; margin-bottom: 0.7rem; }
.cb-botoes-janela button {
  background: var(--painel); border: 0.06rem solid var(--linha); color: var(--texto);
  padding: 0.3rem 0.8rem; border-radius: 0.4rem; cursor: pointer; font-size: 0.85rem;
}
.cb-botoes-janela button[aria-pressed="true"] { border-color: var(--gold); color: var(--navy); font-weight: 700; }

.cb-comp-barra-linha { display: flex; align-items: center; height: 1.9rem; gap: 0.6rem; }
.cb-comp-barra-linha .rot { width: 5.5rem; font-size: 0.85rem; }
.cb-comp-campo { position: relative; flex: 1; height: 1.1rem; background: var(--painel); border-radius: 0.2rem; }
.cb-comp-zero { position: absolute; top: -0.15rem; bottom: -0.15rem; left: 50%; width: 0.08rem; background: var(--linha); }
.cb-comp-valor { position: absolute; top: 0; height: 100%; border-radius: 0.15rem; }
.cb-comp-rotulo { position: absolute; top: 50%; transform: translateY(-50%); font-size: 0.75rem; font-weight: 700; white-space: nowrap; }
.cb-comp-escala { font-size: 0.72rem; color: var(--cinza); margin-bottom: 0.4rem; }

.cb-cards-destaque { display: flex; flex-direction: column; gap: 0.6rem; }
.cb-card-destaque { border: 0.06rem solid var(--linha); border-radius: 0.5rem; padding: 0.6rem 0.8rem; background: var(--painel); }
.cb-card-destaque .cb-card-topo { display: flex; justify-content: space-between; align-items: center; gap: 0.6rem; cursor: pointer; }
.cb-card-destaque .cb-card-topo .cb-card-titulo { font-weight: 700; color: var(--navy); }
.cb-card-destaque .cb-card-resumo { font-size: 0.82rem; color: var(--cinza); margin-top: 0.15rem; }
.cb-card-destaque .cb-card-corpo { display: none; margin-top: 0.6rem; font-size: 0.85rem; }
.cb-card-destaque .cb-card-corpo.aberto { display: block; }
.cb-card-destaque .cb-card-corpo p { margin: 0 0 0.4rem; }
.cb-card-destaque .cb-card-corpo b { color: var(--navy); }
.cb-card-destaque .cb-card-fonte { font-size: 0.75rem; color: var(--cinza); }
.cb-card-destaque .cb-card-fonte a { color: var(--navy); }
.cb-card-destaque:focus-visible, .cb-card-topo:focus-visible { outline: 0.13rem solid var(--gold); outline-offset: 0.1rem; }
.cb-card-seta { color: var(--gold); font-size: 0.8rem; }

.cb-legenda-lista { display: flex; flex-direction: column; gap: 0.4rem; }
.cb-legenda-item { display: flex; align-items: baseline; gap: 0.6rem; font-size: 0.85rem; }

.cb-vazio-nota { font-size: 0.82rem; color: var(--cinza); font-style: italic; }

.cb-rodape { font-size: 0.78rem; color: var(--cinza); border-top: 0.06rem solid var(--linha); padding-top: 0.6rem; text-align: center; }
"""


HTML_ESQUELETO = """<title>{titulo}</title>
<style>{css}</style>
<div class="cb-raiz" id="cb-app">
  <div class="cb-cabecalho">
    <div>
      <h1>Carteira Brasil</h1>
      <div id="cb-cabecalho-sub" class="cb-meta"></div>
    </div>
    <div>
      <button type="button" class="cb-botao-tema" id="cb-botao-tema" aria-pressed="false">Tema claro/escuro</button>
    </div>
  </div>

  <div class="cb-secao">
    <h2>Carteira &times; Ibovespa</h2>
    <div class="cb-resumo-carteira" id="cb-resumo-carteira"></div>
  </div>

  <div class="cb-secao">
    <h2>Heatmap — Dia / 5P / 21P</h2>
    <p class="cb-vazio-nota">Passe o mouse sobre uma célula para ver o valor exato e a leitura do ativo.</p>
    <div class="cb-scroll-x"><div id="cb-heatmap"></div></div>
  </div>

  <div class="cb-secao">
    <h2>Ranking</h2>
    <p class="cb-vazio-nota">Clique no cabeçalho de uma coluna para reordenar (valores sem dado ficam sempre ao final).</p>
    <div class="cb-scroll-x"><div id="cb-ranking"></div></div>
  </div>

  <div class="cb-secao">
    <h2>Comparação carteira &times; Ibovespa</h2>
    <div class="cb-botoes-janela" id="cb-botoes-janela" role="group" aria-label="Escolha da janela"></div>
    <div id="cb-comparativo"></div>
  </div>

  <div class="cb-secao">
    <h2>Destaques</h2>
    <div id="cb-destaques"></div>
  </div>

  <div class="cb-secao">
    <h2>Legenda das leituras</h2>
    <div class="cb-legenda-lista" id="cb-legenda"></div>
  </div>

  <div class="cb-secao">
    <h2>Tabela completa (acessível, sem cor)</h2>
    <div class="cb-scroll-x"><div id="cb-tabela-completa"></div></div>
  </div>

  <div class="cb-rodape">Este material é análise editorial informativa, não recomendação de investimento personalizada.</div>
</div>
<div class="cb-tooltip" id="cb-tooltip" role="tooltip"></div>

<script>
const DADOS = {{"dataset": {dataset_json}, "editorial": {editorial_json}}};
{js}
</script>
"""


JS = r"""
(function () {
  "use strict";
  const MENOS = "−";

  function agrupaMilhar(intpart) {
    return intpart.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  }
  function numValido(v) {
    if (v === null || v === undefined) return null;
    const f = Number(v);
    if (!isFinite(f)) return null;
    return f;
  }
  function fmtNumero(v, casas) {
    casas = casas === undefined ? 2 : casas;
    const f0 = numValido(v);
    if (f0 === null) return "n/d";
    const neg = f0 < 0;
    const f = Math.abs(f0);
    const s = f.toFixed(casas);
    const partes = s.split(".");
    const intPart = agrupaMilhar(partes[0]);
    let out = casas > 0 ? intPart + "," + partes[1] : intPart;
    if (neg) out = MENOS + out;
    return out;
  }
  function fmtVar(v, casas, unidade) {
    casas = casas === undefined ? 2 : casas;
    unidade = unidade === undefined ? "%" : unidade;
    const f = numValido(v);
    if (f === null) return "n/d";
    let sinal = "";
    if (f > 0) sinal = "+";
    else if (f < 0) sinal = MENOS;
    const corpo = fmtNumero(Math.abs(f), casas);
    return unidade ? sinal + corpo + " " + unidade : sinal + corpo;
  }
  function slugLeitura(leitura) {
    if (!leitura) return "sem-dados";
    const semAcento = leitura.normalize("NFKD").replace(/[̀-ͯ]/g, "");
    return semAcento.trim().toLowerCase().replace(/\s+/g, "-");
  }
  function classePct(v) {
    const f = numValido(v);
    if (f === null) return "";
    if (f > 0) return "cb-pos";
    if (f < 0) return "cb-neg";
    return "";
  }
  function hexParaRgb(h) {
    h = h.replace("#", "");
    return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
  }
  function rgbParaHex(rgb) {
    return "#" + rgb.map(c => {
      const n = Math.max(0, Math.min(255, Math.round(c)));
      const s = n.toString(16).toUpperCase();
      return s.length === 1 ? "0" + s : s;
    }).join("");
  }
  function mistura(hexA, hexB, t) {
    t = Math.max(0, Math.min(1, t));
    const a = hexParaRgb(hexA), b = hexParaRgb(hexB);
    return rgbParaHex([a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t, a[2]+(b[2]-a[2])*t]);
  }
  function luminanciaRelativa(hexcor) {
    const [r,g,b] = hexParaRgb(hexcor).map(c => {
      c = c/255;
      return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4);
    });
    return 0.2126*r + 0.7152*g + 0.0722*b;
  }
  function razaoContraste(h1, h2) {
    const l1 = luminanciaRelativa(h1), l2 = luminanciaRelativa(h2);
    const hi = Math.max(l1,l2), lo = Math.min(l1,l2);
    return (hi+0.05)/(lo+0.05);
  }
  function textoParaFundo(fundoHex) {
    const escuro = "#0B2340", claro = "#FFFFFF";
    return razaoContraste(fundoHex, escuro) >= razaoContraste(fundoHex, claro) ? escuro : claro;
  }
  function esc(s) {
    const d = document.createElement("div");
    d.textContent = (s === null || s === undefined) ? "" : String(s);
    return d.innerHTML;
  }
  function get(obj) {
    let cur = obj;
    for (let i = 1; i < arguments.length; i++) {
      if (cur === null || cur === undefined) return null;
      cur = cur[arguments[i]];
    }
    return cur === undefined ? null : cur;
  }

  const dataset = DADOS.dataset || {};
  const editorial = DADOS.editorial || {};
  const ativos = dataset.ativos || [];
  const macro = dataset.macro || {};
  const carteira = dataset.carteira || {};
  const ibov = dataset.ibov || {};
  const cobertura = dataset.cobertura || {};

  // Paleta de dados: lida de dataset.paleta quando presente (mesmos hexes
  // validados usados no PDF), com fallback caso a chave esteja ausente.
  const PALETA_FALLBACK = {
    pos: "#007EA4", neg: "#972700", fav: "#007EA4",
    aten: "#B45309", neut: "#2B3138", semd: "#A9AFB5"
  };
  function hexValido(v) {
    return typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v.trim());
  }
  const PALETA = Object.assign({}, PALETA_FALLBACK);
  if (dataset.paleta && typeof dataset.paleta === "object") {
    Object.keys(PALETA_FALLBACK).forEach(function (k) {
      if (hexValido(dataset.paleta[k])) PALETA[k] = dataset.paleta[k].trim();
    });
  }

  // ---------- Cabeçalho ----------
  (function renderCabecalho() {
    const edicao = dataset.edicao, D = dataset.D;
    const validos = get(cobertura, "validos"), total = get(cobertura, "total");
    let aviso = "";
    if (edicao && D && edicao !== D) {
      aviso = " &middot; A edição de " + esc(edicao) + " analisa o pregão de " + esc(D) + ".";
    }
    document.getElementById("cb-cabecalho-sub").innerHTML =
      "Edição: <b>" + esc(edicao || "n/d") + "</b> &middot; D: <b>" + esc(D || "n/d") + "</b>" +
      " &middot; Cobertura: <b>" + esc(fmtNumero(validos,0)) + "/" + esc(fmtNumero(total,0)) + "</b>" + aviso;
  })();

  (function renderResumoCarteira() {
    const janelas = [["dia","Dia"], ["d5","5P"], ["d21","21P"]];
    const alvo = document.getElementById("cb-resumo-carteira");
    alvo.innerHTML = janelas.map(function (jw) {
      const chave = jw[0], rot = jw[1];
      const cv = get(carteira, chave, "valor");
      const iv = get(ibov, chave);
      const clsC = classePct(cv), clsI = classePct(iv);
      return '<div class="cb-resumo-item"><div class="rot">' + esc(rot) + '</div>' +
        '<div class="linha">Cart. <b class="' + clsC + '" data-campo="carteira.' + chave + '.valor" data-valor="' + esc(cv) + '">' + esc(fmtVar(cv,2,"%")) + '</b></div>' +
        '<div class="linha">Ibov <b class="' + clsI + '" data-campo="ibov.' + chave + '" data-valor="' + esc(iv) + '">' + esc(fmtVar(iv,2,"%")) + '</b></div></div>';
    }).join("");
  })();

  // ---------- Heatmap ----------
  function renderHeatmap() {
    const colunas = [["dia","Dia"], ["d5","5P"], ["d21","21P"]];
    const escalas = {};
    colunas.forEach(function (c) {
      const vals = ativos.map(a => numValido(a[c[0]])).filter(v => v !== null).map(Math.abs);
      escalas[c[0]] = vals.length ? Math.max.apply(null, vals) : 1;
      if (!escalas[c[0]]) escalas[c[0]] = 1;
    });
    let linhas = ativos.map(function (a) {
      const celulas = colunas.map(function (c) {
        const v = a[c[0]];
        const fv = numValido(v);
        if (fv === null) {
          return '<td class="num"><span class="cb-celula-hm" style="background:#E8EAED;color:#5A6875;" ' +
            'data-ticker="' + esc(a.ticker) + '" data-empresa="' + esc(a.empresa) + '" data-leitura="' + esc(a.leitura) + '" data-janela="' + esc(c[1]) + '">n/d</span></td>';
        }
        const intensidade = Math.min(Math.abs(fv) / escalas[c[0]], 1);
        const t = 0.14 + 0.86 * intensidade;
        const base = fv >= 0 ? PALETA.pos : PALETA.neg;
        const fundo = mistura("#FFFFFF", base, t);
        const corTxt = textoParaFundo(fundo);
        return '<td class="num"><span class="cb-celula-hm" style="background:' + fundo + ';color:' + corTxt + ';" ' +
          'data-ticker="' + esc(a.ticker) + '" data-empresa="' + esc(a.empresa) + '" data-leitura="' + esc(a.leitura) + '" ' +
          'data-janela="' + esc(c[1]) + '">' + esc(fmtVar(fv,2,"%")) + '</span></td>';
      }).join("");
      return '<tr><td><b>' + esc(a.ticker) + '</b> <span style="color:var(--cinza)">' + esc(a.empresa) + '</span></td>' + celulas + '</tr>';
    }).join("");
    const cab = colunas.map(c => '<th class="num">' + esc(c[1]) + '</th>').join("");
    document.getElementById("cb-heatmap").innerHTML =
      '<table class="cb-tabela"><thead><tr><th>Ticker / Empresa</th>' + cab + '</tr></thead><tbody>' + linhas + '</tbody></table>';

    const tooltip = document.getElementById("cb-tooltip");
    document.querySelectorAll("#cb-heatmap .cb-celula-hm").forEach(function (el) {
      el.addEventListener("mouseenter", function (ev) {
        const valorTexto = el.textContent;
        tooltip.innerHTML = "<b>" + esc(el.getAttribute("data-ticker")) + "</b> — " + esc(el.getAttribute("data-empresa")) +
          "<br>" + esc(el.getAttribute("data-janela")) + ": " + esc(valorTexto) +
          "<br>Leitura: " + esc(el.getAttribute("data-leitura"));
        tooltip.style.display = "block";
      });
      el.addEventListener("mousemove", function (ev) {
        tooltip.style.left = (ev.clientX + 12) + "px";
        tooltip.style.top = (ev.clientY + 12) + "px";
      });
      el.addEventListener("mouseleave", function () { tooltip.style.display = "none"; });
    });
  }
  renderHeatmap();

  // ---------- Ranking ----------
  let ordemAtual = { coluna: "d21", direcao: "desc" };
  function renderRanking() {
    const colunas = [["ticker","Ticker",false], ["empresa","Empresa",false], ["dia","Dia",true], ["d5","5P",true], ["d21","21P",true], ["leitura","Leitura",false]];
    let lista = ativos.slice();
    const chaveOrd = ordemAtual.coluna;
    lista.sort(function (a, b) {
      const va = numValido(a[chaveOrd]), vb = numValido(b[chaveOrd]);
      if (typeof a[chaveOrd] === "string" || va === null && vb === null) {
        const sa = (a[chaveOrd] || ""), sb = (b[chaveOrd] || "");
        if (typeof sa === "string") {
          const cmp = sa.localeCompare(sb, "pt-BR");
          return ordemAtual.direcao === "asc" ? cmp : -cmp;
        }
      }
      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      return ordemAtual.direcao === "asc" ? va - vb : vb - va;
    });
    const cab = colunas.map(function (c) {
      if (!c[2]) return "<th>" + esc(c[1]) + "</th>";
      const ativo = ordemAtual.coluna === c[0];
      const seta = ativo ? (ordemAtual.direcao === "asc" ? " ▲" : " ▼") : "";
      return '<th class="num cb-ordenavel" data-coluna="' + c[0] + '" tabindex="0" role="button" ' +
        'aria-sort="' + (ativo ? (ordemAtual.direcao === "asc" ? "ascending" : "descending") : "none") + '">' +
        esc(c[1]) + '<span class="cb-seta">' + seta + '</span></th>';
    }).join("");
    const linhas = lista.map(function (a) {
      const slug = slugLeitura(a.leitura);
      return "<tr><td><b>" + esc(a.ticker) + "</b></td><td>" + esc(a.empresa) + "</td>" +
        '<td class="num ' + classePct(a.dia) + '">' + esc(fmtVar(a.dia,2,"%")) + "</td>" +
        '<td class="num ' + classePct(a.d5) + '">' + esc(fmtVar(a.d5,2,"%")) + "</td>" +
        '<td class="num ' + classePct(a.d21) + '">' + esc(fmtVar(a.d21,2,"%")) + "</td>" +
        '<td><span class="cb-pilula ' + slug + '">' + esc(a.leitura || "SEM DADOS") + "</span></td></tr>";
    }).join("");
    document.getElementById("cb-ranking").innerHTML =
      '<table class="cb-tabela"><thead><tr>' + cab + '</tr></thead><tbody>' + linhas + '</tbody></table>';

    document.querySelectorAll("#cb-ranking th.cb-ordenavel").forEach(function (th) {
      function ativa() {
        const col = th.getAttribute("data-coluna");
        if (ordemAtual.coluna === col) {
          ordemAtual.direcao = ordemAtual.direcao === "asc" ? "desc" : "asc";
        } else {
          ordemAtual = { coluna: col, direcao: "desc" };
        }
        renderRanking();
      }
      th.addEventListener("click", ativa);
      th.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); ativa(); }
      });
    });
  }
  renderRanking();

  // ---------- Comparativo ----------
  let janelaAtiva = "dia";
  function renderBotoesJanela() {
    const janelas = [["dia","Dia"], ["d5","5P"], ["d21","21P"]];
    const alvo = document.getElementById("cb-botoes-janela");
    alvo.innerHTML = janelas.map(function (j) {
      return '<button type="button" data-janela="' + j[0] + '" aria-pressed="' + (janelaAtiva === j[0]) + '">' + esc(j[1]) + '</button>';
    }).join("");
    alvo.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        janelaAtiva = b.getAttribute("data-janela");
        renderBotoesJanela();
        renderComparativo();
      });
    });
  }
  function barraComp(rotulo, valor, escala) {
    const fv = numValido(valor);
    if (fv === null) {
      return '<div class="cb-comp-barra-linha"><div class="rot">' + esc(rotulo) + '</div>' +
        '<div class="cb-comp-campo"></div><div style="font-size:0.78rem;color:var(--cinza);font-style:italic;">n/d</div></div>';
    }
    let pctPos = 50 + (fv / escala) * 50;
    pctPos = Math.max(1, Math.min(99, pctPos));
    const esquerda = Math.min(50, pctPos);
    const largura = Math.abs(pctPos - 50);
    const cor = fv >= 0 ? "var(--pos)" : "var(--neg)";
    const dentro = largura > 38;
    const corRot = dentro ? "#FFFFFF" : (fv >= 0 ? "var(--navy)" : "var(--neg)");
    const posRot = dentro
      ? ("left: calc(" + esquerda + "% + 0.2rem);")
      : (fv >= 0 ? ("left: calc(" + (esquerda+largura) + "% + 0.3rem);") : ("right: calc(" + (100-esquerda) + "% + 0.3rem);"));
    return '<div class="cb-comp-barra-linha"><div class="rot">' + esc(rotulo) + '</div>' +
      '<div class="cb-comp-campo"><div class="cb-comp-zero"></div>' +
      '<div class="cb-comp-valor" style="left:' + esquerda + '%;width:' + largura + '%;background:' + cor + ';"></div>' +
      '<span class="cb-comp-rotulo" style="' + posRot + 'color:' + corRot + ';">' + esc(fmtVar(fv,2,"%")) + '</span></div></div>';
  }
  function renderComparativo() {
    const rotJanela = { dia: "Dia", d5: "5P", d21: "21P" }[janelaAtiva];
    const n = get(carteira, janelaAtiva, "n");
    const cv = get(carteira, janelaAtiva, "valor");
    const iv = get(ibov, janelaAtiva);
    const alvo = document.getElementById("cb-comparativo");
    if (n !== null && numValido(n) !== null && n < 12) {
      alvo.innerHTML = '<div class="cb-vazio-nota">Painel omitido: apenas ' + esc(fmtNumero(n,0)) +
        ' ativos com janela ' + esc(rotJanela) + ' válida (mínimo de 12 exigido).</div>';
      return;
    }
    const vals = [numValido(cv), numValido(iv)].filter(v => v !== null).map(Math.abs);
    let escala = vals.length ? Math.max.apply(null, vals) : 1;
    escala = Math.round(escala * 1.15 * 10) / 10 || 1;
    alvo.innerHTML = '<div class="cb-comp-escala">escala: ' + MENOS + fmtNumero(escala,1) + ' % a +' + fmtNumero(escala,1) + ' %</div>' +
      barraComp("Carteira", cv, escala) + barraComp("Ibovespa", iv, escala);
  }
  renderBotoesJanela();
  renderComparativo();

  // ---------- Destaques ----------
  (function renderDestaques() {
    const destaques = (editorial.destaques || []).slice(0, 5);
    const alvo = document.getElementById("cb-destaques");
    let html = "";
    if (destaques.length) {
      html += '<div class="cb-cards-destaque">' + destaques.map(function (d, i) {
        const slug = slugLeitura(d.leitura);
        const fonte = d.fonte || {};
        let fonteHtml = "";
        if (fonte.veiculo || fonte.url) {
          const rotuloFonte = esc(fonte.veiculo || "fonte") + (fonte.data ? " &middot; " + esc(fonte.data) : "");
          fonteHtml = fonte.url
            ? '<div class="cb-card-fonte">Fonte: <a href="' + esc(fonte.url) + '" target="_blank" rel="noopener">' + rotuloFonte + '</a></div>'
            : '<div class="cb-card-fonte">Fonte: ' + rotuloFonte + '</div>';
        }
        const idBase = "cb-destaque-" + i;
        return '<div class="cb-card-destaque">' +
          '<div class="cb-card-topo" role="button" tabindex="0" aria-expanded="false" aria-controls="' + idBase + '-corpo" id="' + idBase + '-topo">' +
          '<div><div class="cb-card-titulo">' + esc(d.ticker) + ' &middot; ' + esc(d.empresa) + '</div>' +
          '<div class="cb-card-resumo">' + esc((d.fato || "").slice(0, 110)) + ((d.fato||"").length > 110 ? "…" : "") + '</div></div>' +
          '<div><span class="cb-pilula ' + slug + '">' + esc(d.leitura || "SEM DADOS") + '</span> <span class="cb-card-seta">▼</span></div>' +
          '</div>' +
          '<div class="cb-card-corpo" id="' + idBase + '-corpo">' +
          '<p><b>Fato:</b> ' + esc(d.fato) + '</p>' +
          '<p><b>Impacto:</b> ' + esc(d.impacto) + '</p>' +
          '<p><b>Risco/contraponto:</b> ' + esc(d.risco) + '</p>' +
          fonteHtml + '</div></div>';
      }).join("") + '</div>';
    }
    if (destaques.length < 3) {
      const comp = editorial.destaques_complemento;
      if (comp && comp.linhas && comp.linhas.length) {
        html += '<div class="cb-card-destaque" style="margin-top:0.6rem;"><div class="cb-card-titulo">' + esc(comp.titulo || "Complemento") + '</div>' +
          '<ul style="margin:0.4rem 0 0 1rem;padding:0;">' + comp.linhas.map(l => "<li>" + esc(l) + "</li>").join("") + '</ul></div>';
      }
    }
    if (!html) html = '<div class="cb-vazio-nota">Nenhum destaque editorial disponível nesta edição.</div>';
    alvo.innerHTML = html;

    alvo.querySelectorAll(".cb-card-topo").forEach(function (topo) {
      function alterna() {
        const corpo = document.getElementById(topo.getAttribute("aria-controls"));
        const aberto = corpo.classList.toggle("aberto");
        topo.setAttribute("aria-expanded", String(aberto));
      }
      topo.addEventListener("click", alterna);
      topo.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); alterna(); }
      });
    });
  })();

  // ---------- Legenda ----------
  (function renderLegenda() {
    const legenda = editorial.legenda || [];
    const alvo = document.getElementById("cb-legenda");
    if (!legenda.length) {
      alvo.innerHTML = '<div class="cb-vazio-nota">Legenda não informada nesta edição.</div>';
      return;
    }
    alvo.innerHTML = legenda.map(function (it) {
      const slug = slugLeitura(it.leitura);
      return '<div class="cb-legenda-item"><span class="cb-pilula ' + slug + '">' + esc(it.leitura) + '</span><span>' + esc(it.texto) + '</span></div>';
    }).join("");
  })();

  // ---------- Tabela completa sem cor ----------
  (function renderTabelaCompleta() {
    const linhas = ativos.map(function (a) {
      return "<tr><td><b>" + esc(a.ticker) + "</b></td><td>" + esc(a.empresa) + "</td>" +
        '<td class="num">' + esc(fmtNumero(a.cotacao,2)) + "</td><td>" + esc(a.ref || "n/d") + "</td>" +
        '<td class="num">' + esc(fmtVar(a.dia,2,"%")) + "</td>" +
        '<td class="num">' + esc(fmtVar(a.d5,2,"%")) + "</td>" +
        '<td class="num">' + esc(fmtVar(a.d21,2,"%")) + "</td>" +
        "<td><span class=\"cb-pilula-contorno\">" + esc(a.leitura || "SEM DADOS") + "</span></td>" +
        "<td>" + esc(a.contexto || "n/d") + "</td></tr>";
    }).join("");
    document.getElementById("cb-tabela-completa").innerHTML =
      '<table class="cb-tabela"><thead><tr><th>Ticker</th><th>Empresa</th><th class="num">Cotação</th><th>Ref.</th>' +
      '<th class="num">Dia</th><th class="num">5P</th><th class="num">21P</th><th>Leitura</th><th>Contexto</th></tr></thead>' +
      "<tbody>" + linhas + "</tbody></table>";
  })();

  // ---------- Tema ----------
  (function configurarTema() {
    const raiz = document.documentElement;
    const botao = document.getElementById("cb-botao-tema");
    const prefereEscuro = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    let atual = prefereEscuro ? "dark" : "light";
    function aplicar() {
      raiz.setAttribute("data-theme", atual);
      botao.setAttribute("aria-pressed", String(atual === "dark"));
    }
    aplicar();
    botao.addEventListener("click", function () {
      atual = atual === "dark" ? "light" : "dark";
      aplicar();
    });
  })();
})();
"""


def montar_html(dataset, editorial):
    titulo = f"Carteira Brasil — {esc(dataset.get('D') or dataset.get('edicao') or 'n/d')}"
    dataset_json = escapa_para_script(json.dumps(dataset, ensure_ascii=False))
    editorial_json = escapa_para_script(json.dumps(editorial, ensure_ascii=False))
    paleta = resolver_paleta(dataset)
    css = css_paleta(paleta) + "\n" + CSS_BASE
    return HTML_ESQUELETO.format(
        titulo=titulo, css=css, dataset_json=dataset_json, editorial_json=editorial_json, js=JS
    )


def main():
    if len(sys.argv) != 4:
        sys.stderr.write("uso: gerador_painel.py <dataset.json> <editorial.json> <saida.html>\n")
        sys.exit(2)
    caminho_dataset, caminho_editorial, caminho_html = sys.argv[1:4]
    dataset = carregar_json(caminho_dataset)
    editorial = carregar_json(caminho_editorial)

    saida = montar_html(dataset, editorial)
    with open(caminho_html, "w", encoding="utf-8") as f:
        f.write(saida)

    print(f"Painel HTML gerado em: {caminho_html}")
    print(f"tamanho: {len(saida)} caracteres")
    print(f"ativos: {len(dataset.get('ativos') or [])}")


if __name__ == "__main__":
    main()
