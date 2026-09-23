// Functional simulation model for the Gowin IDDR primitive used by top.v.
// Hardware synthesis uses the vendor primitive from the Gowin technology map.
module IDDR #(
    parameter Q0_INIT = 1'b0,
    parameter Q1_INIT = 1'b0
) (
    input  wire D,
    input  wire CLK,
    output reg  Q0,
    output reg  Q1
);
    reg falling_sample;

    initial begin
        Q0 = Q0_INIT;
        Q1 = Q1_INIT;
        falling_sample = Q1_INIT;
    end

    always @(negedge CLK)
        falling_sample <= D;

    always @(posedge CLK) begin
        Q0 <= D;
        Q1 <= falling_sample;
    end
endmodule
