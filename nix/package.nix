{ lib, python3Packages }:

python3Packages.buildPythonApplication {
  pname = "ttspeak";
  version = "0.1.0";
  pyproject = true;

  src = lib.cleanSource ../.;

  build-system = [ python3Packages.setuptools ];

  nativeCheckInputs = [ python3Packages.pytestCheckHook ];
  pythonImportsCheck = [ "ttspeak" ];

  meta = {
    description = "Ollama-style local text-to-speech for Apple Silicon (Qwen3-TTS via MLX)";
    homepage = "https://github.com/LukasLow/ttspeak";
    license = lib.licenses.mit;
    mainProgram = "ttspeak";
    platforms = lib.platforms.darwin ++ lib.platforms.linux;
  };
}
