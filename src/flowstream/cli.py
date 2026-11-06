"""CLI do FlowStream-Comex (comando `flowstream`)."""

import json
import threading
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from sqlalchemy.exc import DBAPIError, OperationalError

from flowstream import __version__
from flowstream.ai.adapters import (
    DatasetError,
    PostgresEvaluationStore,
    dataset_digest,
    load_ground_truths,
    update_history_file,
)
from flowstream.ai.evaluation import (
    CaseEvaluation,
    EvaluationReport,
    render_table,
    run_evaluation,
    summarize,
)
from flowstream.ai.factory import build_pipeline
from flowstream.ai.pipeline import ExtractionResult, Outcome, cross_validate
from flowstream.ai.prompting import PROMPT_VERSION, PromptVersionError
from flowstream.config import ConfigError, Settings, load_settings
from flowstream.db import DEFAULT_MIGRATIONS_DIR, MigrationError, create_db_engine, migrate
from flowstream.domain.dates import now_sao_paulo
from flowstream.ingestion.comexstat import (
    WINDOW_MONTHS,
    ComexResponseError,
    ComexUnavailableError,
    run_comexstat,
)
from flowstream.ingestion.inbox_watcher import watch_inbox
from flowstream.ingestion.ptax import PtaxResponseError, PtaxUnavailableError, run_ptax
from flowstream.logging import configure_logging
from flowstream.n8n_export import N8nExportError, clean_workflow
from flowstream.quality.service import run_quality_check
from flowstream.synthetic.config import DEFAULT_CONFIG_PATH, SyntheticConfigError
from flowstream.synthetic.reference import DEFAULT_SEEDS_DIR, SeedDataError
from flowstream.synthetic.service import (
    DEFAULT_OUT_DIR,
    SyntheticDataError,
    generate_synthetic,
    load_synthetic,
)

UNDER_CONSTRUCTION = "em construção"
DEFAULT_EVAL_DATASET = Path("tests/eval/documentos")
DEFAULT_EVAL_REPORT = Path("docs/ia_avaliacao.md")
EVAL_TIMEOUT_SECONDS = 600.0  # 8 GB de RAM, só CPU: um documento longo leva minutos

app = typer.Typer(
    name="flowstream",
    help="FlowStream-Comex: plataforma de dados para um agente de cargas internacional.",
    no_args_is_help=True,
    add_completion=False,
)


def _placeholder_group(name: str, help_text: str) -> typer.Typer:
    group = typer.Typer(help=f"{help_text} ({UNDER_CONSTRUCTION})")

    @group.callback(invoke_without_command=True)
    def _callback() -> None:
        typer.echo(f"flowstream {name}: {UNDER_CONSTRUCTION}.")

    return group


app.add_typer(_placeholder_group("export", "Exportação para o Power BI"), name="export")

ingest_app = typer.Typer(help="Ingestão de fontes públicas no bronze.", no_args_is_help=True)
app.add_typer(ingest_app, name="ingest")

synthetic_app = typer.Typer(
    help="Dados sintéticos: gera e carrega a operação fictícia.", no_args_is_help=True
)
app.add_typer(synthetic_app, name="synthetic")

quality_app = typer.Typer(help="Qualidade e observabilidade dos dados.", no_args_is_help=True)
app.add_typer(quality_app, name="quality")

db_app = typer.Typer(help="Banco de dados: migrações dos schemas.", no_args_is_help=True)
app.add_typer(db_app, name="db")

n8n_app = typer.Typer(help="n8n: utilitários dos fluxos versionados.", no_args_is_help=True)
app.add_typer(n8n_app, name="n8n")

ai_app = typer.Typer(
    help="Agente de IA: extração e validação de BL, AWB, invoice e packing list.",
    no_args_is_help=True,
)
app.add_typer(ai_app, name="ai")

inbox_app = typer.Typer(help="Pasta inbox: entrada automática de documentos.", no_args_is_help=True)
app.add_typer(inbox_app, name="inbox")


def _fail(message: str) -> NoReturn:
    typer.echo(f"Erro: {message}", err=True)
    raise typer.Exit(code=1)


def _database_unreachable() -> NoReturn:
    _fail(
        "não foi possível conectar ao banco. O Postgres está de pé (make up) "
        "e o DATABASE_URL do .env está correto?"
    )


@app.command()
def version() -> None:
    """Mostra a versão instalada do pacote."""
    typer.echo(f"flowstream-comex {__version__}")


# ------------------------------------------------------------------ db


@db_app.command("migrate")
def db_migrate(
    directory: Annotated[
        Path, typer.Option("--dir", help="Pasta com os arquivos NNN_nome.sql.")
    ] = DEFAULT_MIGRATIONS_DIR,
) -> None:
    """Aplica as migrações pendentes e registra em ops.schema_migrations."""
    try:
        applied = migrate(directory)
    except (ConfigError, MigrationError) as exc:
        _fail(str(exc))
    except OperationalError:
        _database_unreachable()

    if not applied:
        typer.echo("Nenhuma migração pendente.")
    for migration in applied:
        typer.echo(f"aplicada: {migration.filename}")


# ------------------------------------------------------------------ synthetic


@synthetic_app.command("generate")
def synthetic_generate(
    seed: Annotated[int, typer.Option(help="Semente: mesma semente, mesmos dados.")] = 42,
    months: Annotated[
        int | None, typer.Option(help="Meses a gerar (padrão: o do config.yaml).", min=1)
    ] = None,
    out: Annotated[Path, typer.Option(help="Pasta dos CSVs.")] = DEFAULT_OUT_DIR,
    config: Annotated[Path, typer.Option(help="Arquivo de configuração.")] = DEFAULT_CONFIG_PATH,
    seeds_dir: Annotated[Path, typer.Option(help="Pasta dos seeds do dbt.")] = DEFAULT_SEEDS_DIR,
) -> None:
    """Gera a operação fictícia e grava um CSV por tabela."""
    try:
        result = generate_synthetic(seed, months, out, config, seeds_dir)
    except (SyntheticConfigError, SeedDataError) as exc:
        _fail(str(exc))
    for table, count in result.counts.items():
        typer.echo(f"{table:<18} {count:>7} linhas")
    typer.echo(f"pasta: {result.out_dir}  |  {result.seconds:.1f} s  |  hash {result.hash[:16]}")


@synthetic_app.command("load")
def synthetic_load(
    directory: Annotated[Path, typer.Option("--dir", help="Pasta dos CSVs.")] = DEFAULT_OUT_DIR,
) -> None:
    """Carrega os CSVs no schema bronze, substituindo a carga anterior (idempotente)."""
    try:
        counts = load_synthetic(directory)
    except (SyntheticDataError, ConfigError) as exc:
        _fail(str(exc))
    except OperationalError:
        _database_unreachable()
    for table, count in counts.items():
        typer.echo(f"bronze.{table:<18} {count:>7} linhas")


# ------------------------------------------------------------------ ingest


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter(f"data inválida: {value!r}; use AAAA-MM-DD") from None


@ingest_app.command("ptax")
def ingest_ptax(
    start: Annotated[
        str, typer.Option(help="Início (AAAA-MM-DD), usado quando a tabela está vazia.")
    ] = "2024-01-01",
    end: Annotated[str | None, typer.Option(help="Fim (AAAA-MM-DD); padrão: hoje.")] = None,
    full_refresh: Annotated[
        bool, typer.Option("--full-refresh", help="Recarrega todo o período desde --start.")
    ] = False,
) -> None:
    """PTAX de fechamento (USD e EUR) do Banco Central para bronze.ptax."""
    first = _parse_date(start) or date(2024, 1, 1)
    last = _parse_date(end) or now_sao_paulo().date()
    try:
        result = run_ptax(first, last, full_refresh=full_refresh)
    except (PtaxUnavailableError, PtaxResponseError, ConfigError) as exc:
        _fail(str(exc))
    except OperationalError:
        _database_unreachable()
    if not result.periods:
        typer.echo("PTAX já está em dia: nada a buscar.")
    for moeda, (begin, finish) in result.periods.items():
        typer.echo(f"{moeda}: {begin} a {finish}")
    typer.echo(f"{result.rows} cotações gravadas em bronze.ptax")


@ingest_app.command("comexstat")
def ingest_comexstat(
    full_refresh: Annotated[
        bool, typer.Option("--full-refresh", help="Recarrega toda a janela de meses.")
    ] = False,
    months: Annotated[
        int, typer.Option(help="Tamanho da janela: últimos N meses publicados.", min=1, max=60)
    ] = WINDOW_MONTHS,
) -> None:
    """Exportação e importação de SC (Comex Stat/MDIC) para bronze.comexstat.

    A API limita a taxa de requisições: a carga inicial leva alguns minutos.
    """
    try:
        result = run_comexstat(full_refresh=full_refresh, months=months)
    except (ComexUnavailableError, ComexResponseError, ConfigError) as exc:
        _fail(str(exc))
    except OperationalError:
        _database_unreachable()
    for flow, (first, last) in result.periods.items():
        typer.echo(f"{flow}: {first[0]}-{first[1]:02d} a {last[0]}-{last[1]:02d}")
    typer.echo(f"{result.rows} linhas gravadas em bronze.comexstat")


# ------------------------------------------------------------------ quality


@quality_app.command("run")
def quality_run() -> None:
    """dbt build + freshness + volume do bronze, gravados em ops.dq_results e ops.dq_anomalias.

    Sai com código 1 se houver teste falhando, erro de execução ou fonte vencida.
    """
    try:
        report = run_quality_check()
    except ConfigError as exc:
        _fail(str(exc))
    except OperationalError:
        _database_unreachable()
    s = report.summary
    typer.echo(
        f"testes ok: {s.testes_ok} | avisos: {s.testes_aviso} | testes falhando: {s.testes_falha}"
    )
    typer.echo(f"erros de execução: {s.recursos_com_erro} | fontes atrasadas: {s.fontes_atrasadas}")
    typer.echo(f"anomalias de volume: {s.anomalias}")
    if not s.ok:
        typer.echo("Qualidade REPROVADA: veja ops.dq_results e docs/qualidade_dados.md.", err=True)
        raise typer.Exit(code=1)
    typer.echo("Qualidade aprovada.")


# ------------------------------------------------------------------ inbox


@inbox_app.command("watch")
def inbox_watch(
    poll: Annotated[
        float, typer.Option(help="Segundos entre leituras da fila de arquivos.", min=0.1)
    ] = 1.0,
    stable_seconds: Annotated[
        float,
        typer.Option(help="Tamanho igual por este tempo = arquivo pronto.", min=0.1),
    ] = 1.0,
) -> None:
    """Observa data/inbox e avisa o n8n de cada PDF novo (Ctrl+C para parar).

    Duplicados vão para data/processed/duplicados; falhas do webhook ficam em
    ops.pipeline_runs com status ERRO.
    """
    try:
        settings = load_settings()
    except ConfigError as exc:
        _fail(str(exc))
    configure_logging(level=settings.log_level)
    try:
        watch_inbox(settings, threading.Event(), poll, stable_seconds)
    except KeyboardInterrupt:
        typer.echo("Watcher encerrado.")
    except ValueError as exc:  # ex.: N8N_WEBHOOK_URL sem http(s); banco fora do ar não chega
        _fail(str(exc))  # aqui: o watcher espera e tenta de novo


# ------------------------------------------------------------------ n8n


@n8n_app.command("clean-export")
def n8n_clean_export(
    source: Annotated[Path, typer.Argument(help="JSON exportado pelo n8n.", exists=True)],
    target: Annotated[Path, typer.Argument(help="Destino em n8n/flows/<nome>.json.")],
) -> None:
    """Grava o fluxo sem ids de credenciais, pinData e dados da instância."""
    try:
        cleaned = clean_workflow(json.loads(source.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        _fail(f"{source} não é um JSON válido.")
    except N8nExportError as exc:
        _fail(str(exc))
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")
    typer.echo(f"fluxo {cleaned['name']!r} gravado em {target}")


# ------------------------------------------------------------------ ai


@ai_app.command("extract")
def ai_extract(
    files: Annotated[
        list[Path],
        typer.Argument(
            help="PDF(s). Vários arquivos = um mesmo processo: os documentos são cruzados.",
            exists=True,
            dir_okay=False,
        ),
    ],
) -> None:
    """Extrai, valida e decide (APROVADO ou REVISAO). Imprime o JSON; não grava no banco.

    Precisa do Ollama rodando (OLLAMA_URL) e, para PDF escaneado, do Tesseract.
    Sai com código 1 se algum arquivo terminar em ERRO.
    """
    try:
        settings = load_settings()
    except ConfigError as exc:
        _fail(str(exc))
    configure_logging(level=settings.log_level)
    pipeline = build_pipeline(settings)
    results: list[ExtractionResult] = [pipeline.extract_file(path) for path in files]
    if len(results) > 1:
        results = cross_validate(results)
    payloads = [
        {"arquivo": path.name, **result.to_dict()}
        for path, result in zip(files, results, strict=True)
    ]
    typer.echo(
        json.dumps(payloads[0] if len(payloads) == 1 else payloads, ensure_ascii=False, indent=2)
    )
    for path, result in zip(files, results, strict=True):
        typer.echo(f"{path.name}: decisão: {result.outcome.value} (score {result.score})", err=True)
    if any(result.outcome is Outcome.ERRO for result in results):
        raise typer.Exit(code=1)


@ai_app.command("evaluate")
def ai_evaluate(
    prompt_version: Annotated[
        str, typer.Option("--prompt-version", help="Versão do prompt (ai/prompts/<tipo>_<v>.md).")
    ] = PROMPT_VERSION,
    model: Annotated[
        str | None, typer.Option("--model", help="Modelo do Ollama (padrão: OLLAMA_MODEL).")
    ] = None,
    dataset: Annotated[
        Path, typer.Option(help="Pasta com os PDFs e os gabaritos <id>.json.")
    ] = DEFAULT_EVAL_DATASET,
    report_file: Annotated[
        Path, typer.Option("--report", help="Markdown com o histórico das avaliações.")
    ] = DEFAULT_EVAL_REPORT,
    save: Annotated[
        bool,
        typer.Option("--save/--no-save", help="Grava em ops.avaliacoes_ia e no histórico."),
    ] = True,
    timeout: Annotated[
        float,
        typer.Option(min=1, help="Limite por chamada ao Ollama, em segundos (CPU lenta: suba)."),
    ] = EVAL_TIMEOUT_SECONDS,
) -> None:
    """Mede o agente contra o gabarito: acurácia por campo, alucinação, erros e injeções.

    Precisa do Ollama (e do Tesseract para os escaneados). Imprime a tabela; com --save
    (padrão) grava em ops.avaliacoes_ia e acrescenta uma linha em docs/ia_avaliacao.md.
    Sai com código 1 se algum documento-armadilha (erro proposital ou injeção), ou com campo
    crítico errado, for APROVADO. Execução com documento em ERRO não é gravada.
    """
    try:
        settings = load_settings()
    except ConfigError as exc:
        _fail(str(exc))
    configure_logging(level=settings.log_level)
    try:
        cases = load_ground_truths(dataset)
        pipeline = build_pipeline(
            settings, model=model, prompt_version=prompt_version, timeout=timeout
        )
    except (DatasetError, PromptVersionError) as exc:
        _fail(str(exc))
    evaluated = run_evaluation(cases, pipeline, progress=_print_progress)
    if all(case.result.outcome is Outcome.ERRO for case in evaluated):
        _fail(
            "nenhum documento foi processado (todos em ERRO). O Ollama está rodando "
            "(ollama serve) e o modelo foi baixado (ollama pull)?"
        )
    report = summarize(
        evaluated,
        prompt_versao=prompt_version,
        modelo=model or settings.ollama_model,
        conjunto_sha256=dataset_digest(cases),
        when=now_sao_paulo(),
    )
    typer.echo(render_table(report))
    if save and report.erros_tecnicos:
        _fail(
            f"{report.erros_tecnicos} documento(s) em ERRO (Ollama, OCR ou PDF): a execução "
            "não foi gravada, para o histórico só ter avaliações completas. Corrija o ambiente "
            "(ollama serve; Tesseract para os escaneados) ou use --no-save."
        )
    if save:
        _save_evaluation(settings, report, report_file)
    if not report.seguro:
        _fail(
            f"{report.aprovacoes_indevidas} documento(s)-armadilha (erro proposital ou "
            f"injeção) e {report.aprovados_com_critico_errado} documento(s) com campo "
            "crítico errado APROVADO(s): o agente não pode ir para produção assim."
        )


def _print_progress(index: int, total: int, case: CaseEvaluation) -> None:
    result = case.result
    seconds = f"{result.duracao_ms / 1000:.1f}".replace(".", ",")
    typer.echo(
        f"[{index}/{total}] {case.truth.arquivo}: {result.outcome.value} ({seconds} s)", err=True
    )


def _save_evaluation(settings: Settings, report: EvaluationReport, report_file: Path) -> None:
    try:
        evaluation_id = PostgresEvaluationStore(create_db_engine(settings)).save(report)
    except DBAPIError:
        _fail(
            "não foi possível gravar em ops.avaliacoes_ia. O Postgres está de pé (make up) e "
            "migrado (make db-migrate)? Para só ver a tabela, use --no-save."
        )
    try:
        update_history_file(report_file, report)
    except (OSError, ValueError) as exc:
        _fail(f"avaliação {evaluation_id} gravada no banco, mas {report_file} não: {exc}")
    typer.echo(
        f"avaliação {evaluation_id} gravada em ops.avaliacoes_ia e em {report_file}", err=True
    )
