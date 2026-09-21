module top (
    input  wire        clk_10mhz,
    input  wire [11:0] adc_data,
    input  wire        uart_rx_pin,
    output wire        uart_tx_pin,
    output wire        adc_pd,
    output wire        status_led,
    output wire        trig_out
);
    localparam [2:0] TX_IDLE    = 3'd0;
    localparam [2:0] TX_HEADER  = 3'd1;
    localparam [2:0] TX_PAYLOAD = 3'd2;
    localparam [2:0] TX_CRC_LO  = 3'd3;
    localparam [2:0] TX_CRC_HI  = 3'd4;

    localparam [1:0] CMD_IDLE   = 2'd0;
    localparam [1:0] CMD_T_LO   = 2'd1;
    localparam [1:0] CMD_T_HI   = 2'd2;
    localparam [1:0] CMD_POL    = 2'd3;

    localparam [7:0] RESP_INFO  = 8'h49; // I
    localparam [7:0] RESP_STATS = 8'h53; // S
    localparam [7:0] RESP_HIST  = 8'h48; // H

    reg [7:0] reset_count = 8'd0;
    wire rst = !reset_count[7];
    always @(posedge clk_10mhz)
        if (!reset_count[7])
            reset_count <= reset_count + 1'b1;

    // ADC12010 updates after the rising edge. Its datasheet recommends
    // capturing the parallel bus on the falling edge of the conversion clock.
    reg [11:0] adc_sample_falling = 12'd2048;
    always @(negedge clk_10mhz)
        adc_sample_falling <= adc_data;

    reg [11:0] adc_sample = 12'd2048;
    always @(posedge clk_10mhz)
        adc_sample <= adc_sample_falling;

    assign adc_pd = 1'b0;

    reg [11:0] threshold = 12'd32;
    // The assembled analog path produces negative-going ADC codes for the
    // user's amplified PMT module.  1 selects baseline-sample.
    reg polarity = 1'b1;
    reg clear_stats_request = 1'b0;
    reg hist_clear_request = 1'b0;
    reg stream_pause = 1'b0;

    wire event_valid;
    wire [11:0] event_bin;
    wire trigger_pulse;
    wire [11:0] current_sample;
    wire [11:0] baseline;
    wire [11:0] adc_min;
    wire [11:0] adc_max;
    wire [11:0] last_peak;
    wire pulse_active;
    wire [31:0] trigger_count;
    wire [31:0] accepted_count;
    wire [31:0] rejected_count;
    wire [31:0] saturated_count;
    wire [63:0] live_samples;

    wire hist_ready;
    wire [31:0] hist_dropped_events;
    reg [11:0] hist_read_address = 12'd0;
    wire [31:0] hist_read_data;

    wire acquisition_enable = hist_ready && !stream_pause;

    mca_engine engine (
        .clk(clk_10mhz),
        .rst(rst),
        .enable(acquisition_enable),
        .clear_stats(clear_stats_request),
        .sample(adc_sample),
        .threshold(threshold),
        .polarity(polarity),
        .event_valid(event_valid),
        .event_bin(event_bin),
        .trigger_pulse(trigger_pulse),
        .current_sample(current_sample),
        .baseline(baseline),
        .adc_min(adc_min),
        .adc_max(adc_max),
        .last_peak(last_peak),
        .pulse_active(pulse_active),
        .trigger_count(trigger_count),
        .accepted_count(accepted_count),
        .rejected_count(rejected_count),
        .saturated_count(saturated_count),
        .live_samples(live_samples)
    );

    histogram spectrum (
        .clk(clk_10mhz),
        .rst(rst),
        .clear_request(hist_clear_request),
        .event_valid(event_valid),
        .event_bin(event_bin),
        .read_address(hist_read_address),
        .read_data(hist_read_data),
        .ready(hist_ready),
        .dropped_events(hist_dropped_events)
    );

    wire [7:0] uart_rx_data;
    wire uart_rx_valid;
    wire uart_framing_error;
    uart_rx #(.CLKS_PER_BIT(10)) receiver (
        .clk(clk_10mhz),
        .rst(rst),
        .rx(uart_rx_pin),
        .data(uart_rx_data),
        .valid(uart_rx_valid),
        .framing_error(uart_framing_error)
    );

    // Only the low byte is reported. Keeping this counter at its actual width
    // avoids a partially-unused wide register that older nextpnr-gowin builds
    // can leave behind as an unplaceable generic $buf cell.
    reg [7:0] uart_error_count = 8'd0;
    always @(posedge clk_10mhz)
        if (rst)
            uart_error_count <= 8'd0;
        else if (uart_framing_error)
            uart_error_count <= uart_error_count + 1'b1;

    reg [2:0] tx_state = TX_IDLE;
    reg [2:0] header_index = 3'd0;
    reg [15:0] payload_index = 16'd0;
    reg [15:0] payload_length = 16'd0;
    reg [7:0] response_type = 8'h00;
    reg [7:0] response_status = 8'h00;
    reg [15:0] response_crc = 16'hffff;

    reg [7:0] ack_command = 8'h00;
    reg [15:0] ack_value = 16'h0000;
    reg [1:0] command_state = CMD_IDLE;
    reg [7:0] threshold_low = 8'h00;

    // Snapshot registers keep a statistics response internally consistent.
    reg [11:0] snap_sample = 12'd0;
    reg [11:0] snap_baseline = 12'd0;
    reg [11:0] snap_min = 12'd0;
    reg [11:0] snap_max = 12'd0;
    reg [11:0] snap_threshold = 12'd0;
    reg snap_polarity = 1'b0;
    reg [7:0] snap_flags = 8'h00;
    reg [31:0] snap_triggers = 32'd0;
    reg [31:0] snap_accepted = 32'd0;
    reg [31:0] snap_rejected = 32'd0;
    reg [31:0] snap_saturated = 32'd0;
    reg [31:0] snap_dropped = 32'd0;
    reg [63:0] snap_live = 64'd0;
    reg [11:0] snap_last_peak = 12'd0;

    function [15:0] crc16_next;
        input [15:0] crc_in;
        input [7:0] byte_in;
        integer bit_number;
        reg [15:0] work;
        begin
            work = crc_in ^ {byte_in, 8'h00};
            for (bit_number = 0; bit_number < 8; bit_number = bit_number + 1)
                if (work[15])
                    work = (work << 1) ^ 16'h1021;
                else
                    work = work << 1;
            crc16_next = work;
        end
    endfunction

    function [7:0] select_u32_byte;
        input [31:0] value;
        input [1:0] byte_number;
        begin
            case (byte_number)
                2'd0: select_u32_byte = value[7:0];
                2'd1: select_u32_byte = value[15:8];
                2'd2: select_u32_byte = value[23:16];
                default: select_u32_byte = value[31:24];
            endcase
        end
    endfunction

    function [7:0] select_u64_byte;
        input [63:0] value;
        input [2:0] byte_number;
        begin
            case (byte_number)
                3'd0: select_u64_byte = value[7:0];
                3'd1: select_u64_byte = value[15:8];
                3'd2: select_u64_byte = value[23:16];
                3'd3: select_u64_byte = value[31:24];
                3'd4: select_u64_byte = value[39:32];
                3'd5: select_u64_byte = value[47:40];
                3'd6: select_u64_byte = value[55:48];
                default: select_u64_byte = value[63:56];
            endcase
        end
    endfunction

    function [7:0] info_byte;
        input [3:0] index;
        begin
            case (index)
                4'd0:  info_byte = 8'd1;    // firmware major
                4'd1:  info_byte = 8'd3;    // firmware minor
                4'd2:  info_byte = 8'd12;   // ADC bits
                4'd3:  info_byte = 8'h01;   // feature bit 0: peak histogram
                4'd4:  info_byte = 8'h80;   // 10,000,000 samples/s, little-endian
                4'd5:  info_byte = 8'h96;
                4'd6:  info_byte = 8'h98;
                4'd7:  info_byte = 8'h00;
                4'd8:  info_byte = 8'h00;   // 4096 channels, little-endian
                4'd9:  info_byte = 8'h10;
                4'd10: info_byte = 8'h40;   // 1,000,000 baud, little-endian
                4'd11: info_byte = 8'h42;
                4'd12: info_byte = 8'h0f;
                4'd13: info_byte = 8'h00;
                4'd14: info_byte = 8'h00;
                default: info_byte = 8'h00;
            endcase
        end
    endfunction

    function [7:0] stats_byte;
        input [5:0] index;
        begin
            case (index)
                6'd0:  stats_byte = snap_sample[7:0];
                6'd1:  stats_byte = {4'd0, snap_sample[11:8]};
                6'd2:  stats_byte = snap_baseline[7:0];
                6'd3:  stats_byte = {4'd0, snap_baseline[11:8]};
                6'd4:  stats_byte = snap_min[7:0];
                6'd5:  stats_byte = {4'd0, snap_min[11:8]};
                6'd6:  stats_byte = snap_max[7:0];
                6'd7:  stats_byte = {4'd0, snap_max[11:8]};
                6'd8:  stats_byte = snap_threshold[7:0];
                6'd9:  stats_byte = {4'd0, snap_threshold[11:8]};
                6'd10: stats_byte = {7'd0, snap_polarity};
                6'd11: stats_byte = snap_flags;
                6'd12, 6'd13, 6'd14, 6'd15:
                    stats_byte = select_u32_byte(snap_triggers, index[1:0]);
                6'd16, 6'd17, 6'd18, 6'd19:
                    stats_byte = select_u32_byte(snap_accepted, index[1:0]);
                6'd20, 6'd21, 6'd22, 6'd23:
                    stats_byte = select_u32_byte(snap_rejected, index[1:0]);
                6'd24, 6'd25, 6'd26, 6'd27:
                    stats_byte = select_u32_byte(snap_saturated, index[1:0]);
                6'd28, 6'd29, 6'd30, 6'd31:
                    stats_byte = select_u32_byte(snap_dropped, index[1:0]);
                6'd32, 6'd33, 6'd34, 6'd35, 6'd36, 6'd37, 6'd38, 6'd39:
                    stats_byte = select_u64_byte(snap_live, index[2:0]);
                6'd40: stats_byte = snap_last_peak[7:0];
                6'd41: stats_byte = {4'd0, snap_last_peak[11:8]};
                6'd42: stats_byte = uart_error_count[7:0];
                default: stats_byte = 8'd0;
            endcase
        end
    endfunction

    reg [7:0] tx_data;
    wire tx_valid = (tx_state != TX_IDLE);
    wire tx_ready;
    wire tx_fire = tx_valid && tx_ready;

    always @* begin
        tx_data = 8'h00;
        case (tx_state)
            TX_HEADER: begin
                case (header_index)
                    3'd0: tx_data = 8'h4d; // M
                    3'd1: tx_data = 8'h43; // C
                    3'd2: tx_data = 8'h41; // A
                    3'd3: tx_data = 8'h31; // 1
                    3'd4: tx_data = response_type;
                    3'd5: tx_data = response_status;
                    3'd6: tx_data = payload_length[7:0];
                    default: tx_data = payload_length[15:8];
                endcase
            end

            TX_PAYLOAD: begin
                if (response_type == RESP_INFO)
                    tx_data = info_byte(payload_index[3:0]);
                else if (response_type == RESP_STATS)
                    tx_data = stats_byte(payload_index[5:0]);
                else if (response_type == RESP_HIST)
                    tx_data = select_u32_byte(hist_read_data, payload_index[1:0]);
                else begin
                    case (payload_index[1:0])
                        2'd0: tx_data = ack_command;
                        2'd1: tx_data = response_status;
                        2'd2: tx_data = ack_value[7:0];
                        default: tx_data = ack_value[15:8];
                    endcase
                end
            end

            TX_CRC_LO: tx_data = response_crc[7:0];
            TX_CRC_HI: tx_data = response_crc[15:8];
            default: tx_data = 8'h00;
        endcase
    end

    uart_tx #(.CLKS_PER_BIT(10)) transmitter (
        .clk(clk_10mhz),
        .rst(rst),
        .data(tx_data),
        .valid(tx_valid),
        .ready(tx_ready),
        .tx(uart_tx_pin)
    );

    always @(posedge clk_10mhz) begin
        clear_stats_request <= 1'b0;
        hist_clear_request <= 1'b0;

        if (rst) begin
            threshold          <= 12'd32;
            polarity           <= 1'b1;
            stream_pause       <= 1'b0;
            tx_state           <= TX_IDLE;
            command_state      <= CMD_IDLE;
            header_index       <= 3'd0;
            payload_index      <= 16'd0;
            payload_length     <= 16'd0;
            response_type      <= 8'h00;
            response_status    <= 8'h00;
            response_crc       <= 16'hffff;
            hist_read_address  <= 12'd0;
            ack_command        <= 8'h00;
            ack_value          <= 16'h0000;
            threshold_low      <= 8'h00;
        end else begin
            if (tx_fire) begin
                case (tx_state)
                    TX_HEADER: begin
                        response_crc <= crc16_next(response_crc, tx_data);
                        if (header_index == 3'd7) begin
                            header_index <= 3'd0;
                            payload_index <= 16'd0;
                            if (payload_length == 16'd0)
                                tx_state <= TX_CRC_LO;
                            else
                                tx_state <= TX_PAYLOAD;
                        end else begin
                            header_index <= header_index + 1'b1;
                        end
                    end

                    TX_PAYLOAD: begin
                        response_crc <= crc16_next(response_crc, tx_data);
                        if ((response_type == RESP_HIST) && (payload_index[1:0] == 2'd3))
                            hist_read_address <= hist_read_address + 1'b1;

                        if (payload_index == payload_length - 1'b1)
                            tx_state <= TX_CRC_LO;
                        else
                            payload_index <= payload_index + 1'b1;
                    end

                    TX_CRC_LO: tx_state <= TX_CRC_HI;

                    TX_CRC_HI: begin
                        tx_state <= TX_IDLE;
                        stream_pause <= 1'b0;
                    end

                    default: tx_state <= TX_IDLE;
                endcase
            end

            if (uart_rx_valid && (tx_state == TX_IDLE)) begin
                case (command_state)
                    CMD_T_LO: begin
                        threshold_low <= uart_rx_data;
                        command_state <= CMD_T_HI;
                    end

                    CMD_T_HI: begin
                        if ({uart_rx_data[3:0], threshold_low} < 12'd4)
                            threshold <= 12'd4;
                        else
                            threshold <= {uart_rx_data[3:0], threshold_low};
                        ack_command     <= 8'h54;
                        ack_value       <= ({uart_rx_data[3:0], threshold_low} < 12'd4) ? 16'd4 : {4'd0, uart_rx_data[3:0], threshold_low};
                        response_type   <= 8'hd4;
                        response_status <= 8'h00;
                        payload_length  <= 16'd4;
                        response_crc    <= 16'hffff;
                        header_index    <= 3'd0;
                        tx_state        <= TX_HEADER;
                        command_state   <= CMD_IDLE;
                    end

                    CMD_POL: begin
                        polarity         <= uart_rx_data[0];
                        ack_command       <= 8'h50;
                        ack_value         <= {15'd0, uart_rx_data[0]};
                        response_type     <= 8'hd0;
                        response_status   <= 8'h00;
                        payload_length    <= 16'd4;
                        response_crc      <= 16'hffff;
                        header_index      <= 3'd0;
                        tx_state          <= TX_HEADER;
                        command_state     <= CMD_IDLE;
                    end

                    default: begin
                        case (uart_rx_data)
                            8'h49: begin // I: firmware information
                                response_type   <= RESP_INFO;
                                response_status <= 8'h00;
                                payload_length  <= 16'd16;
                                response_crc    <= 16'hffff;
                                header_index    <= 3'd0;
                                tx_state        <= TX_HEADER;
                            end

                            8'h53: begin // S: statistics snapshot
                                snap_sample      <= current_sample;
                                snap_baseline    <= baseline;
                                snap_min         <= adc_min;
                                snap_max         <= adc_max;
                                snap_threshold   <= threshold;
                                snap_polarity    <= polarity;
                                snap_flags       <= {4'd0, stream_pause, pulse_active, hist_ready, acquisition_enable};
                                snap_triggers    <= trigger_count;
                                snap_accepted    <= accepted_count;
                                snap_rejected    <= rejected_count;
                                snap_saturated   <= saturated_count;
                                snap_dropped     <= hist_dropped_events;
                                snap_live        <= live_samples;
                                snap_last_peak   <= last_peak;
                                response_type    <= RESP_STATS;
                                response_status  <= 8'h00;
                                payload_length   <= 16'd44;
                                response_crc     <= 16'hffff;
                                header_index     <= 3'd0;
                                tx_state         <= TX_HEADER;
                            end

                            8'h48: begin // H: full 4096 x 32-bit histogram
                                response_type   <= RESP_HIST;
                                response_crc    <= 16'hffff;
                                header_index    <= 3'd0;
                                hist_read_address <= 12'd0;
                                if (hist_ready) begin
                                    response_status <= 8'h00;
                                    payload_length  <= 16'd16384;
                                    stream_pause    <= 1'b1;
                                end else begin
                                    response_status <= 8'h01;
                                    payload_length  <= 16'd0;
                                end
                                tx_state <= TX_HEADER;
                            end

                            8'h43: begin // C: clear spectrum and statistics
                                hist_clear_request  <= 1'b1;
                                clear_stats_request <= 1'b1;
                                ack_command         <= 8'h43;
                                ack_value           <= 16'd0;
                                response_type       <= 8'hc3;
                                response_status     <= 8'h00;
                                payload_length      <= 16'd4;
                                response_crc        <= 16'hffff;
                                header_index        <= 3'd0;
                                tx_state            <= TX_HEADER;
                            end

                            8'h54: command_state <= CMD_T_LO; // T + uint16 threshold
                            8'h50: command_state <= CMD_POL;  // P + uint8 polarity

                            default: begin
                                ack_command       <= uart_rx_data;
                                ack_value         <= 16'd0;
                                response_type     <= 8'hff;
                                response_status   <= 8'h02;
                                payload_length    <= 16'd4;
                                response_crc      <= 16'hffff;
                                header_index      <= 3'd0;
                                tx_state          <= TX_HEADER;
                            end
                        endcase
                    end
                endcase
            end
        end
    end

    reg [22:0] heartbeat = 23'd0;
    reg [16:0] event_flash = 17'd0;
    reg [3:0] trigger_width = 4'd0;
    always @(posedge clk_10mhz) begin
        if (rst) begin
            heartbeat    <= 23'd0;
            event_flash  <= 17'd0;
            trigger_width <= 4'd0;
        end else begin
            heartbeat <= heartbeat + 1'b1;
            if (trigger_pulse) begin
                event_flash   <= 17'd100000; // 10 ms visible event flash
                trigger_width <= 4'd10;      // 1 us trigger output
            end else begin
                if (event_flash != 0)
                    event_flash <= event_flash - 1'b1;
                if (trigger_width != 0)
                    trigger_width <= trigger_width - 1'b1;
            end
        end
    end

    assign status_led = heartbeat[22] | (event_flash != 0);
    assign trig_out = (trigger_width != 0);
endmodule
