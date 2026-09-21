module mca_engine (
    input  wire        clk,
    input  wire        rst,
    input  wire        enable,
    input  wire        clear_stats,
    input  wire [11:0] sample,
    input  wire [11:0] threshold,
    input  wire        polarity,
    output reg         event_valid = 1'b0,
    output reg  [11:0] event_bin = 12'd0,
    output reg         trigger_pulse = 1'b0,
    output reg  [11:0] current_sample = 12'd2048,
    output wire [11:0] baseline,
    output reg  [11:0] adc_min = 12'hfff,
    output reg  [11:0] adc_max = 12'h000,
    output reg  [11:0] last_peak = 12'd0,
    output wire        pulse_active,
    output reg  [31:0] trigger_count = 32'd0,
    output reg  [31:0] accepted_count = 32'd0,
    output reg  [31:0] rejected_count = 32'd0,
    output reg  [31:0] saturated_count = 32'd0,
    output reg  [63:0] live_samples = 64'd0
);
    localparam [1:0] ST_IDLE    = 2'd0;
    localparam [1:0] ST_TRACK   = 2'd1;
    localparam [1:0] ST_RECOVER = 2'd2;

    localparam [9:0]  MAX_PULSE_SAMPLES      = 10'd1023;
    localparam [13:0] NORMAL_RECOVERY_SAMPLES = 14'd8;
    localparam [13:0] SAT_RECOVERY_SAMPLES    = 14'd10000; // 1 ms at 10 MSPS

    reg [1:0] state = ST_IDLE;
    reg signed [20:0] baseline_acc = 21'sd524288; // 2048 in Q12.8
    reg [11:0] peak = 12'd0;
    reg [9:0] pulse_length = 10'd0;
    reg [2:0] quiet_count = 3'd0;
    reg [13:0] recovery_count = 14'd0;
    reg pulse_saturated = 1'b0;

    wire signed [20:0] sample_q8 = $signed({1'b0, sample, 8'b0});
    wire signed [20:0] baseline_error = sample_q8 - baseline_acc;
    wire signed [20:0] baseline_step = baseline_error >>> 8;

    assign baseline = baseline_acc[19:8];
    assign pulse_active = (state == ST_TRACK);

    wire [11:0] positive_amplitude =
        (sample >= baseline) ? sample - baseline : 12'd0;
    wire [11:0] negative_amplitude =
        (baseline >= sample) ? baseline - sample : 12'd0;
    wire [11:0] amplitude = polarity ? negative_amplitude : positive_amplitude;
    wire [11:0] opposite_amplitude = polarity ? positive_amplitude : negative_amplitude;
    wire [11:0] release_level = {1'b0, threshold[11:1]};
    wire [11:0] peak_candidate = (amplitude > peak) ? amplitude : peak;
    wire saturation_now = pulse_saturated || (sample >= 12'd4094) || (sample <= 12'd1);

    always @(posedge clk) begin
        event_valid  <= 1'b0;
        trigger_pulse <= 1'b0;

        if (rst) begin
            state             <= ST_IDLE;
            baseline_acc      <= 21'sd524288;
            peak              <= 12'd0;
            pulse_length      <= 10'd0;
            quiet_count       <= 3'd0;
            recovery_count    <= 14'd0;
            pulse_saturated   <= 1'b0;
            event_bin         <= 12'd0;
            current_sample    <= 12'd2048;
            adc_min           <= 12'hfff;
            adc_max           <= 12'h000;
            last_peak         <= 12'd0;
            trigger_count     <= 32'd0;
            accepted_count    <= 32'd0;
            rejected_count    <= 32'd0;
            saturated_count   <= 32'd0;
            live_samples      <= 64'd0;
        end else begin
            current_sample <= sample;

            // Clearing must take priority over acquisition.  Previously the
            // live-sample increment later in this clocked block overwrote the
            // zero assigned here, so elapsed time could never be reset.
            if (clear_stats) begin
                state             <= ST_IDLE;
                peak              <= 12'd0;
                pulse_length      <= 10'd0;
                quiet_count       <= 3'd0;
                recovery_count    <= 14'd0;
                pulse_saturated   <= 1'b0;
                adc_min         <= 12'hfff;
                adc_max         <= 12'h000;
                last_peak       <= 12'd0;
                trigger_count   <= 32'd0;
                accepted_count  <= 32'd0;
                rejected_count  <= 32'd0;
                saturated_count <= 32'd0;
                live_samples    <= 64'd0;
            end else if (!enable) begin
                state           <= ST_IDLE;
                peak            <= 12'd0;
                pulse_length    <= 10'd0;
                quiet_count     <= 3'd0;
                recovery_count  <= 14'd0;
                pulse_saturated <= 1'b0;
            end else begin
                live_samples <= live_samples + 1'b1;
                if (sample < adc_min)
                    adc_min <= sample;
                if (sample > adc_max)
                    adc_max <= sample;

                case (state)
                    ST_IDLE: begin
                        peak            <= 12'd0;
                        pulse_length    <= 10'd0;
                        quiet_count     <= 3'd0;
                        pulse_saturated <= 1'b0;

                        if (amplitude >= threshold) begin
                            peak            <= amplitude;
                            pulse_length    <= 10'd1;
                            pulse_saturated <= (sample >= 12'd4094) || (sample <= 12'd1);
                            trigger_count   <= trigger_count + 1'b1;
                            trigger_pulse   <= 1'b1;
                            state           <= ST_TRACK;
                        end else if (opposite_amplitude < threshold) begin
                            // Track the baseline only while the sample is
                            // close to it in both directions.  A large
                            // opposite-polarity overshoot used to drag the
                            // baseline to a rail and create thousands of
                            // false retriggers after one clipped pulse.
                            baseline_acc <= baseline_acc + baseline_step;
                        end
                    end

                    ST_TRACK: begin
                        peak            <= peak_candidate;
                        pulse_saturated <= saturation_now;
                        pulse_length    <= pulse_length + 1'b1;

                        if (pulse_length == MAX_PULSE_SAMPLES) begin
                            rejected_count <= rejected_count + 1'b1;
                            if (saturation_now) begin
                                saturated_count <= saturated_count + 1'b1;
                                recovery_count  <= SAT_RECOVERY_SAMPLES;
                            end else begin
                                recovery_count <= NORMAL_RECOVERY_SAMPLES;
                            end
                            state <= ST_RECOVER;
                        end else if (amplitude <= release_level) begin
                            if (quiet_count == 3'd3) begin
                                last_peak <= peak_candidate;
                                if (saturation_now) begin
                                    rejected_count  <= rejected_count + 1'b1;
                                    saturated_count <= saturated_count + 1'b1;
                                    recovery_count  <= SAT_RECOVERY_SAMPLES;
                                end else begin
                                    event_bin      <= peak_candidate;
                                    event_valid    <= 1'b1;
                                    accepted_count <= accepted_count + 1'b1;
                                    recovery_count <= NORMAL_RECOVERY_SAMPLES;
                                end
                                quiet_count <= 3'd0;
                                state <= ST_RECOVER;
                            end else begin
                                quiet_count <= quiet_count + 1'b1;
                            end
                        end else begin
                            quiet_count <= 3'd0;
                        end
                    end

                    ST_RECOVER: begin
                        if (recovery_count == 4'd0)
                            state <= ST_IDLE;
                        else
                            recovery_count <= recovery_count - 1'b1;
                    end

                    default: state <= ST_IDLE;
                endcase
            end
        end
    end
endmodule
