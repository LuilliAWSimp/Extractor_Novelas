# Novel Archiver Project

Proyecto para archivar novelas web de forma autorizada y exportarlas a TXT, EPUB y PDF simple.

## Soporte actual

- `nova`
- `generic`
- `novelaenespanol`

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Uso básico

### Descubrir desde URL base

```bash
python cli.py --url "https://novelaenespanol.com/novela-ligera/llord-of-the-mysteriess-es/" --parser novelaenespanol --formats epub,txt --limit 3 --output novels_output
```

### Usar lista manual de capítulos

```bash
python cli.py --chapter-list chapters.txt --parser nova --formats epub,txt --title "Lord of Mysteries" --language es --output novels_output
```

Formato de `chapters.txt`:

```text
1|Capítulo 1|https://...
2|Capítulo 2|https://...
```

O también:

```text
1|https://...
2|https://...
```

## Estructura esperada

```text
novel_archiver_project/
├── cli.py
├── requirements.txt
├── README.md
├── examples/
└── novel_archiver/
    ├── __init__.py
    ├── archive.py
    ├── http.py
    ├── models.py
    ├── runner.py
    ├── text_utils.py
    ├── exporters/
    └── parsers/
```

La carpeta `novel_archiver/` es normal: es el paquete Python principal del proyecto. No es un duplicado del repo, es la carpeta interna del código.


## Debug y validación de rangos

Ejemplo para validar un volumen y fallar si queda incompleto:

```bash
python cli.py --url "https://novelaenespanol.com/novela-ligera/llord-of-the-mysteriess-es/" --parser novelaenespanol --start 214 --end 482 --seed-url "https://novelaenespanol.com/llord-of-the-mysteriess-es/novela-ligera/lotm-senor-de-los-misterios-capitulo-214-tierra-de-esperanza/" --formats epub,txt --debug-crawl --fail-incomplete --output novels_output
```


## Interfaz web local

Puedes ejecutar una interfaz local estilo formulario para lanzar la descarga sin usar la consola:

```bash
python web_ui.py
```

Luego abre en el navegador:

```text
http://127.0.0.1:5000
```

La web permite indicar:

- URL base
- parser
- capítulo inicial y final
- seed URL opcional
- formatos a generar
- debug crawl
- fail incomplete
- delay, timeout y reintentos

Y muestra:

- progreso
- logs
- validación del rango
- motivo de parada del crawler
- archivos generados
- botón para abrir la carpeta de salida
