module uart_rx #(
    parameter integer CLKS_PER_BIT = 10
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       rx,
    output reg  [7:0] data = 8'h00,
    output reg        valid = 1'b0,
    output reg        framing_error = 1'b0
);
    localparam [1:0] ST_IDLE  = 2'd0;
    localparam [1:0] ST_START = 2'd1;
    localparam [1:0] ST_DATA  = 2'd2;
    localparam [1:0] ST_STOP  = 2'd3;

    reg rx_meta = 1'b1;
    reg rx_sync = 1'b1;
    reg [1:0] state = ST_IDLE;
    reg [7:0] shift = 8'h00;
    reg [3:0] clock_count = 4'd0;
    reg [2:0] bit_index = 3'd0;

    always @(posedge clk) begin
        rx_meta <= rx;
        rx_sync <= rx_meta;

        valid <= 1'b0;
        framing_error <= 1'b0;

        if (rst) begin
            state       <= ST_IDLE;
            shift       <= 8'h00;
            clock_count <= 4'd0;
            bit_index   <= 3'd0;
            data        <= 8'h00;
        end else begin
            case (state)
                ST_IDLE: begin
                    clock_count <= 4'd0;
                    if (!rx_sync)
                        state <= ST_START;
                end

                ST_START: begin
                    if (clock_count == (CLKS_PER_BIT / 2) - 1) begin
                        clock_count <= 4'd0;
                        if (!rx_sync) begin
                            bit_index <= 3'd0;
                            state <= ST_DATA;
                        end else begin
                            state <= ST_IDLE;
                        end
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end

                ST_DATA: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count      <= 4'd0;
                        shift[bit_index] <= rx_sync;
                        if (bit_index == 3'd7)
                            state <= ST_STOP;
                        else
                            bit_index <= bit_index + 1'b1;
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end

                ST_STOP: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 4'd0;
                        data        <= shift;
                        valid       <= rx_sync;
                        framing_error <= !rx_sync;
                        state       <= ST_IDLE;
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
            endcase
        end
    end
endmodule
