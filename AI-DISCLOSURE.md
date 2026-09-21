# AI-assisted development disclosure

The Aster MCA FPGA firmware, HDL testbenches, Python host utility, and parts of
the technical documentation were written and refined with assistance from
OpenAI Codex/ChatGPT.

AI-generated or AI-suggested material was not treated as independent evidence
that the instrument worked. The released firmware was checked with HDL
simulation, host-side protocol tests, complete synthesis and place-and-route,
timing analysis, and operation on the physical prototype. Detector connection,
bench measurements, source placement, hardware rework, and final acceptance
were performed by the human project owner.

Known design mistakes and prototype repairs are documented openly in
`docs/hardware-errata-v0.1.md`. Contributors should review AI-assisted changes
with the same care as any other untrusted contribution and should distinguish
simulation, inspection, and physical measurement in future reports.
