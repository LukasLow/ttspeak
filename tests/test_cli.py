import json


def test_version_and_help(run_cli):
    version = run_cli("--version")
    assert version.returncode == 0
    assert "ttspeak 0.1.0" in version.stdout

    help_result = run_cli("--help")
    assert help_result.returncode == 0
    assert "Usage:" in help_result.stdout


def test_shortcut_synthesis(run_cli, env):
    result = run_cli(
        "Hallo Welt",
        "-m",
        "fake:custom",
        "--engine",
        "mock",
        "--no-play",
        "-o",
        "out.wav",
    )
    assert result.returncode == 0, result.stderr
    assert (env.tmp / "out.wav").is_file()
    assert "Wrote" in result.stdout


def test_flags_before_text(run_cli, env):
    result = run_cli(
        "--model",
        "fake:custom",
        "--engine",
        "mock",
        "--no-play",
        "-o",
        "flags.wav",
        "Hallo",
    )
    assert result.returncode == 0, result.stderr
    assert (env.tmp / "flags.wav").is_file()


def test_pull_list_show_rm(run_cli, env):
    pull = run_cli("pull", "fake:custom")
    assert pull.returncode == 0, pull.stderr
    assert "Pulled fake:custom" in pull.stdout

    listing = run_cli("list")
    assert listing.returncode == 0
    assert "fake:custom" in listing.stdout

    show = run_cli("show", "fake:custom")
    assert show.returncode == 0
    assert "Installed:   yes" in show.stdout
    assert "Serena" in show.stdout

    rm = run_cli("rm", "fake:custom", "--yes")
    assert rm.returncode == 0, rm.stderr
    assert not (env.root / "models" / "fake-custom").exists()


def test_pull_twice_is_idempotent(run_cli):
    first = run_cli("pull", "fake:custom")
    second = run_cli("pull", "fake:custom")
    assert first.returncode == 0
    assert second.returncode == 0
    assert "already installed" in second.stdout


def test_search(run_cli):
    result = run_cli("search", "fake")
    assert result.returncode == 0
    assert "fake:custom" in result.stdout
    assert "fake:base" in result.stdout


def test_config_set_get_list_unset(run_cli):
    set_result = run_cli("config", "set", "model", "fake:custom")
    assert set_result.returncode == 0, set_result.stderr

    get_result = run_cli("config", "get", "model")
    assert get_result.returncode == 0
    assert get_result.stdout.strip() == "fake:custom"

    listing = run_cli("config", "list")
    assert "user" in listing.stdout
    assert "fake:custom" in listing.stdout

    unset = run_cli("config", "unset", "model")
    assert unset.returncode == 0
    assert run_cli("config", "get", "model").stdout.strip() == "voxtral:4b"


def test_synthesis_uses_config_model(run_cli, env):
    assert run_cli("config", "set", "model", "fake:custom").returncode == 0
    result = run_cli("Hallo", "--engine", "mock", "--no-play", "-o", "configured.wav")
    assert result.returncode == 0, result.stderr
    assert (env.tmp / "configured.wav").is_file()


def test_run_command(run_cli, env):
    result = run_cli("run", "fake:custom", "Hallo", "--engine", "mock", "--no-play", "-o", "run.wav")
    assert result.returncode == 0, result.stderr
    assert (env.tmp / "run.wav").is_file()


def test_json_output(run_cli):
    result = run_cli(
        "Hallo",
        "-m",
        "fake:custom",
        "--engine",
        "mock",
        "--no-play",
        "-o",
        "json.wav",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["model"] == "fake:custom"
    assert data["voice"] == "Serena"
    assert data["language"] == "German"
    assert data["output"].endswith("json.wav")


def test_voice_add_list_rm(run_cli, env, reference_wav):
    assert run_cli("pull", "fake:base").returncode == 0
    add = run_cli(
        "voice",
        "add",
        "Lukas",
        "--audio",
        str(reference_wav),
        "--text",
        "Hallo, ich bin Lukas.",
        "--model",
        "fake:base",
    )
    assert add.returncode == 0, add.stderr
    assert (env.root / "voices" / "lukas" / "profile.json").is_file()

    listing = run_cli("voices")
    assert "Lukas" in listing.stdout
    assert "fake:base" in listing.stdout

    show = run_cli("voice", "show", "Lukas", "--json")
    assert json.loads(show.stdout)["name"] == "Lukas"

    rm = run_cli("voice", "rm", "Lukas", "--yes")
    assert rm.returncode == 0, rm.stderr
    assert not (env.root / "voices" / "lukas").exists()


def test_voice_prune(run_cli, env, reference_wav):
    assert run_cli("pull", "fake:base").returncode == 0
    for name in ("Lukas", "Anna"):
        result = run_cli(
            "voice",
            "add",
            name,
            "--audio",
            str(reference_wav),
            "--text",
            "Hallo.",
            "--model",
            "fake:base",
        )
        assert result.returncode == 0, result.stderr
    prune = run_cli("voice", "prune", "--keep", "Lukas", "--yes")
    assert prune.returncode == 0, prune.stderr
    assert not (env.root / "voices" / "anna").exists()
    assert (env.root / "voices" / "lukas").exists()


def test_prune(run_cli, env):
    assert run_cli("pull", "fake:custom").returncode == 0
    assert run_cli("pull", "fake:base").returncode == 0
    result = run_cli("prune", "--keep", "fake:custom", "--yes")
    assert result.returncode == 0, result.stderr
    assert "fake:base" in result.stdout
    assert not (env.root / "models" / "fake-base").exists()
    assert (env.root / "models" / "fake-custom").exists()


def test_unknown_model_is_a_clean_error(run_cli):
    result = run_cli("show", "does:not-exist")
    assert result.returncode == 1
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr
