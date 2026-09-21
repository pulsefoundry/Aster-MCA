# Cs-137 example data

- `source-943s.csv` — 943.493 s source acquisition, 4096 bins.
- `background-30s.csv` — 30.017 s background acquisition, 4096 bins.

Both files contain two columns: `channel,counts`. The runs used firmware v1.3,
threshold 32, negative-going pulses, and analog gain near ×3.33. Normalize each
file by its FPGA live time before subtracting the background.

The corresponding plot and analysis caveats are in `docs/validation.md`.
