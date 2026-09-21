module uart_tx #(
    parameter integer CLKS_PER_BIT = 10
) (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] data,
    input  wire       valid,
    output wire       ready,
    output reg        tx = 1'b1
);
    localparam [1:0] ST_IDLE  = 2'd0;
    localparam [1:0] ST_START = 2'd1;
    localparam [1:0] ST_DATA  = 2'd2;
    localparam [1:0] ST_STOP  = 2'd3;

    reg [1:0] state = ST_IDLE;
    reg [7:0] shift = 8'h00;
    reg [3:0] clock_count = 4'd0;
    reg [2:0] bit_index = 3'd0;

    assign ready = (state == ST_IDLE);

    always @(posedge clk) begin
        if (rst) begin
            state       <= ST_IDLE;
            shift       <= 8'h00;
            clock_count <= 4'd0;
            bit_index   <= 3'd0;
            tx          <= 1'b1;
        end else begin
            case (state)
                ST_IDLE: begin
                    tx <= 1'b1;
                    if (valid) begin
                        shift       <= data;
                        clock_count <= 4'd0;
                        tx          <= 1'b0;
                        state       <= ST_START;
                    end
                end

                ST_START: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 4'd0;
                        bit_index   <= 3'd0;
                        tx          <= shift[0];
                        state       <= ST_DATA;
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end

                ST_DATA: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 4'd0;
                        if (bit_index == 3'd7) begin
                            tx    <= 1'b1;
                            state <= ST_STOP;
                        end else begin
                            bit_index <= bit_index + 1'b1;
                            tx        <= shift[bit_index + 1'b1];
                        end
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end

                ST_STOP: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 4'd0;
                        state       <= ST_IDLE;
                        tx          <= 1'b1;
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
            endcase
        end
    end
endmodule
