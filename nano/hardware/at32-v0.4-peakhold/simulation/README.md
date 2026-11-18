# Positive peak-hold simulation results

These are circuit-model results, not measured hardware performance or energy resolution. The final circuit in this package converts negative input pulses to positive RAW pulses about a nominal 0.623 V reference and holds their positive peak.

- `simulation-summary.json`: final result ranges, assumptions and model limitations.
- `simulated-peak-hold.png`: representative waveform plot.
- `validate_positive.json`: 48 deliberately sharp triangular peak cases across supply, amplitude and rise time.
- `validate_frontend.json`: 12 finite sin-squared input cases, including the inverting front end.
- `tolerance_check.json`: representative capacitance and feedback-parasitic cases.
- `positive-candidate.cir`: final positive-capture test circuit, excluding the TLV9062 input stage.
- `representative.cir`: 0.5 V, 4 us sin-squared negative input and a later pulse while held.
- `tolerance.cir`: the last saved tolerance case (CH = 493.5 pF, CF = 2.2 pF), not a sweep driver; the JSON contains all 12 sweep results.

See [model sources and setup](MODEL-SOURCES.md) before attempting to run the circuits. They intentionally reference external supplier macro-model files that are not redistributed here. Run a copy in a scratch directory: the control sections write transient output files. The supplied JSON and PNG are retained independently of regenerated scratch outputs.

The modeled smooth 4 us test pulse does not establish the error for every pulse with the same total width. Abrupt triangular tips expose substantially larger errors. Switch charge injection, feedthrough, real switch capacitance, component production corners, layout, leakage, ADC kickback and full dual-amplifier package coupling are not fully modeled. The reference voltage is ideal in these transient tests. Follow the bench checks in the electrical review before interpreting spectra.
