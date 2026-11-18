# External model sources

Supplier models are excluded from this MIT-licensed delivery. Obtain them from their authors under the terms supplied with each download; preserve their notices. The original circuit decks are supplied, but no vendor `.LIB`, model ZIP, vendor schematic or vendor PDF is included.

| Required file relative to the circuit deck | Official source | Use in this simulation |
|---|---|---|
| `opa356-model/OPA356_PSPICE_AIO/OPA356.LIB` | [TI OPA356 PSpice model, SBOM848](https://www.ti.com/lit/zip/sbom848) | Two single-channel OPA356 models approximate the OPA2356 driver and buffer. This does not model dual-package coupling. |
| `vendor-model/tlv9062.lib` | [TI TLV9062 PSpice model, SBOMAG1](https://www.ti.com/lit/zip/sbomag1) | Front-end inverting amplifier. Required by the representative and tolerance decks. |

Unpack the two official archives and place the indicated `.LIB` files at those relative paths, or edit the `.include` lines to your chosen local paths. The model file paths and subcircuit names are case-sensitive on some systems. The saved results were produced with ngspice 47 in PSpice compatibility mode:

```sh
ngspice -D ngbehavior=ps -b representative.cir
```

The decks use local analytical diode models named `DBAS316` and `DBAS70` and a simplified `SW1` model for the switch. These are engineering approximations, not vendor-qualified models. In particular, the switch model does not establish TMUX1136 charge injection or feedthrough performance. Circuit parameters and conclusions are bounded by `simulation-summary.json` and the electrical review.

Relevant device documentation: [OPA2356](https://www.ti.com/lit/ds/symlink/opa2356.pdf), [TLV9062](https://www.ti.com/lit/ds/symlink/tlv9062.pdf), [TMUX1136](https://www.ti.com/lit/ds/symlink/tmux1136.pdf), [TLV3201](https://www.ti.com/lit/ds/symlink/tlv3201.pdf), [BAS316](https://assets.nexperia.com/documents/data-sheet/BAS316.pdf), [BAS70-04](https://assets.nexperia.com/documents/data-sheet/BAS70-04.pdf).
