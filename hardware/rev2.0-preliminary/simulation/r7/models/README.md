# THS4551 vendor model

The TI macro-model is not copied into this project. Download **THS4551 PSpice
Model, SBOMB92B.ZIP** from:

<https://www.ti.com/lit/zip/sbomb92>

Extract `ths4551.lib`, then run:

```sh
python3 ../run_simulations.py --model /path/to/ths4551.lib
```

Alternatively, `--fetch-model` retrieves the same archive directly from TI.
`prepare_ti_model.py` converts three PSpice `TABLE` sources to native ngspice
behavioural PWL sources with the same point pairs and normalizes switch model
threshold syntax. Generated vendor-derived files stay under `work/` and are not
part of the project sources.
