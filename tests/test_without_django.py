import subprocess
import sys


def test_core_imports_without_django():
    code = (
        "import sys; sys.modules['django'] = None\n"
        "import llm_localize.cli, llm_localize.engine, llm_localize.formats.po\n"
        "import llm_localize.providers.openai\n"
        "from llm_localize.languages import language_name\n"
        "assert language_name('fr') == 'French'"
    )

    subprocess.run([sys.executable, "-c", code], check=True)
