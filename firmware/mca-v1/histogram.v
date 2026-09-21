module histogram (
    input  wire        clk,
    input  wire        rst,
    input  wire        clear_request,
    input  wire        event_valid,
    input  wire [11:0] event_bin,
    input  wire [11:0] read_address,
    output reg  [31:0] read_data = 32'd0,
    output wire        ready,
    output reg  [31:0] dropped_events = 32'd0
);
    localparam [2:0] ST_CLEAR = 3'd0;
    localparam [2:0] ST_IDLE  = 3'd1;
    localparam [2:0] ST_WAIT  = 3'd2;
    localparam [2:0] ST_WRITE = 3'd3;

    (* ram_style = "block" *) reg [31:0] memory [0:4095];

    reg [2:0] state = ST_CLEAR;
    reg [11:0] clear_address = 12'd0;
    reg [11:0] pending_bin = 12'd0;
    reg [31:0] memory_read_data = 32'd0;

    // A simple-dual-port organization uses one BSRAM port only for writes and
    // the other only for reads. Event read-modify-write and host spectrum
    // reads share the read port; acquisition is paused during host transfer.
    wire [11:0] memory_read_address =
        ((state == ST_WAIT) || (state == ST_WRITE)) ? pending_bin : read_address;
    wire [11:0] memory_write_address =
        (state == ST_CLEAR) ? clear_address : pending_bin;
    wire memory_write_enable = (state == ST_CLEAR) || (state == ST_WRITE);
    wire [31:0] memory_write_data =
        (state == ST_CLEAR) ? 32'd0 : memory_read_data + 1'b1;

    assign ready = (state == ST_IDLE);
    always @*
        read_data = memory_read_data;

    always @(posedge clk) begin
        memory_read_data <= memory[memory_read_address];
        if (memory_write_enable)
            memory[memory_write_address] <= memory_write_data;
    end

    always @(posedge clk) begin
        if (rst || clear_request) begin
            state          <= ST_CLEAR;
            clear_address  <= 12'd0;
            pending_bin    <= 12'd0;
            dropped_events <= 32'd0;
        end else begin
            case (state)
                ST_CLEAR: begin
                    if (clear_address == 12'hfff) begin
                        clear_address <= 12'd0;
                        state <= ST_IDLE;
                    end else begin
                        clear_address <= clear_address + 1'b1;
                    end
                end

                ST_IDLE: begin
                    if (event_valid) begin
                        pending_bin <= event_bin;
                        state <= ST_WAIT;
                    end
                end

                ST_WAIT: begin
                    if (event_valid)
                        dropped_events <= dropped_events + 1'b1;
                    state <= ST_WRITE;
                end

                ST_WRITE: begin
                    if (event_valid)
                        dropped_events <= dropped_events + 1'b1;
                    state <= ST_IDLE;
                end
            endcase
        end
    end
endmodule
