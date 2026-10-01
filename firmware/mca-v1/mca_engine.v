module mca_engine (
    input  wire        clk,
    input  wire        rst,
    input  wire        enable,
    input  wire        clear_stats,
    input  wire [11:0] sample,
    input  wire [11:0] threshold,
    input  wire        polarity,
    input  wire [2:0]  energy_mode,
    output reg         event_valid = 1'b0,
    output reg  [11:0] event_bin = 12'd0,
    output reg         trigger_pulse = 1'b0,
    output reg  [11:0] current_sample = 12'd2048,
    output wire [11:0] baseline,
    output reg  [11:0] adc_min = 12'hfff,
    output reg  [11:0] adc_max = 12'h000,
    output reg  [11:0] last_peak = 12'd0,
    output reg  [11:0] last_energy = 12'd0,
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
    localparam [9:0]  AREA_GATE_SAMPLES       = 10'd64;
    localparam [13:0] NORMAL_RECOVERY_SAMPLES = 14'd8;
    localparam [13:0] SAT_RECOVERY_SAMPLES    = 14'd10000; // 1 ms at 10 MSPS

    reg [1:0] state = ST_IDLE;
    reg signed [20:0] baseline_acc = 21'sd524288; // 2048 in Q12.8
    reg [11:0] peak = 12'd0;
    reg [21:0] area = 22'd0;
    reg [9:0] pulse_length = 10'd0;
    reg [2:0] quiet_count = 3'd0;
    reg [13:0] recovery_count = 14'd0;
    reg pulse_saturated = 1'b0;
    reg trigger_pending = 1'b0;
    reg [11:0] pending_amplitude = 12'd0;
    reg pending_saturated = 1'b0;

    // Four-sample boxcar filtering suppresses isolated ADC-code excursions
    // while preserving the peak of the roughly microsecond-wide detector
    // pulses used by Aster MCA.  A second consecutive over-threshold filtered
    // sample is required before a trigger is accepted.
    reg [11:0] sample_d1 = 12'd2048;
    reg [11:0] sample_d2 = 12'd2048;
    reg [11:0] sample_d3 = 12'd2048;
    reg [3:0] saturation_history = 4'd0;

    localparam integer TRAP_RISE = 16;
    localparam integer TRAP_GAP = 4;
    localparam integer TRAP_DELAY = (2 * TRAP_RISE) + TRAP_GAP;
    reg [39:0] trap_saturation_history = 40'd0;
    wire [13:0] filtered_sum =
        {2'd0, sample} + {2'd0, sample_d1} +
        {2'd0, sample_d2} + {2'd0, sample_d3};
    wire [11:0] filtered_sample = (filtered_sum + 14'd2) >> 2;
    wire raw_saturation = (sample >= 12'd4094) || (sample <= 12'd1);
    wire saturation_recent = raw_saturation || (|saturation_history);

    // A 16-sample rise window, a 4-sample flat-top gap, and a second
    // 16-sample window form a compact trapezoidal FIR.  Subtracting the old
    // window from the recent window removes slow tails while summing coherent
    // pulse samples.  At 10 MSPS the shaping time is 1.6 us and the gap is
    // 0.4 us, close to the measured detector-pulse time scale.
    reg signed [12:0] trap_delay [0:TRAP_DELAY-1];
    reg signed [17:0] trap_recent_sum = 18'sd0;
    reg signed [17:0] trap_old_sum = 18'sd0;
    integer trap_index;

    wire signed [20:0] sample_q8 = $signed({1'b0, filtered_sample, 8'b0});
    wire signed [20:0] baseline_error = sample_q8 - baseline_acc;
    wire signed [20:0] baseline_step = baseline_error >>> 8;

    assign baseline = baseline_acc[19:8];
    assign pulse_active = (state == ST_TRACK);

    wire [11:0] positive_amplitude =
        (filtered_sample >= baseline) ? filtered_sample - baseline : 12'd0;
    wire [11:0] negative_amplitude =
        (baseline >= filtered_sample) ? baseline - filtered_sample : 12'd0;
    wire [11:0] amplitude = polarity ? negative_amplitude : positive_amplitude;
    wire [11:0] opposite_amplitude = polarity ? positive_amplitude : negative_amplitude;
    wire signed [12:0] signed_sample_delta =
        $signed({1'b0, filtered_sample}) - $signed({1'b0, baseline});
    wire signed [12:0] trap_input =
        polarity ? -signed_sample_delta : signed_sample_delta;
    wire signed [18:0] trap_difference =
        $signed({trap_recent_sum[17], trap_recent_sum}) -
        $signed({trap_old_sum[17], trap_old_sum});
    wire [18:0] trap_positive = trap_difference[18] ? 19'd0 : trap_difference;
    wire trapezoid_mode = (energy_mode >= 3'd5);
    wire [18:0] trap_scaled =
        (energy_mode == 3'd5) ? (trap_positive >> 2) :
        (energy_mode == 3'd6) ? (trap_positive >> 3) :
                                (trap_positive >> 4);
    wire trap_overrange = |trap_scaled[18:12];
    wire [11:0] trap_energy =
        trap_overrange ? 12'hfff : trap_scaled[11:0];
    wire [11:0] trigger_metric = trapezoid_mode ? trap_energy : amplitude;
    wire [11:0] measured_energy = trapezoid_mode ? trap_energy : amplitude;
    wire [11:0] release_level = {1'b0, threshold[11:1]};
    wire [11:0] peak_candidate = (measured_energy > peak) ? measured_energy : peak;
    wire [21:0] area_candidate =
        (pulse_length < AREA_GATE_SAMPLES) ?
            area + {10'd0, amplitude} : area;
    wire saturation_for_mode = trapezoid_mode ?
        (raw_saturation || (|trap_saturation_history) || trap_overrange) :
        saturation_recent;
    wire saturation_now = pulse_saturated || saturation_for_mode;
    wire [11:0] trigger_peak =
        (measured_energy > pending_amplitude) ? measured_energy : pending_amplitude;

    // Pulse-area modes integrate the full baseline-subtracted amplitude, but
    // only inside a fixed 64-sample gate (6.4 us at 10 MSPS).  This keeps the
    // measured energy independent of the user-selected trigger threshold.
    // Detector pulses are about 2 us wide, while long baseline excursions
    // otherwise create false high-energy events.  The selectable power-of-two
    // divisor avoids a multiplier.  Values above the histogram range saturate
    // at bin 4095.
    function [11:0] area_to_bin;
        input [21:0] area_value;
        input [2:0] mode;
        reg [21:0] scaled;
        begin
            case (mode)
                3'd1: scaled = area_value;
                3'd2: scaled = area_value >> 1;
                3'd3: scaled = area_value >> 2;
                default: scaled = area_value >> 3;
            endcase
            area_to_bin = (|scaled[21:12]) ? 12'hfff : scaled[11:0];
        end
    endfunction

    wire [11:0] energy_candidate =
        ((energy_mode == 3'd0) || trapezoid_mode) ?
            peak_candidate : area_to_bin(area_candidate, energy_mode);

    always @(posedge clk) begin
        event_valid  <= 1'b0;
        trigger_pulse <= 1'b0;

        if (rst) begin
            state             <= ST_IDLE;
            baseline_acc      <= 21'sd524288;
            peak              <= 12'd0;
            area              <= 22'd0;
            pulse_length      <= 10'd0;
            quiet_count       <= 3'd0;
            recovery_count    <= 14'd0;
            pulse_saturated   <= 1'b0;
            trigger_pending   <= 1'b0;
            pending_amplitude <= 12'd0;
            pending_saturated <= 1'b0;
            sample_d1         <= 12'd2048;
            sample_d2         <= 12'd2048;
            sample_d3         <= 12'd2048;
            saturation_history <= 4'd0;
            trap_saturation_history <= 40'd0;
            trap_recent_sum   <= 18'sd0;
            trap_old_sum      <= 18'sd0;
            for (trap_index = 0; trap_index < TRAP_DELAY; trap_index = trap_index + 1)
                trap_delay[trap_index] <= 13'sd0;
            event_bin         <= 12'd0;
            current_sample    <= 12'd2048;
            adc_min           <= 12'hfff;
            adc_max           <= 12'h000;
            last_peak         <= 12'd0;
            last_energy       <= 12'd0;
            trigger_count     <= 32'd0;
            accepted_count    <= 32'd0;
            rejected_count    <= 32'd0;
            saturated_count   <= 32'd0;
            live_samples      <= 64'd0;
        end else begin
            current_sample <= sample;
            sample_d1 <= sample;
            sample_d2 <= sample_d1;
            sample_d3 <= sample_d2;
            saturation_history <= {saturation_history[2:0], raw_saturation};
            trap_saturation_history <= {trap_saturation_history[38:0], raw_saturation};
            trap_recent_sum <= trap_recent_sum + trap_input - trap_delay[TRAP_RISE-1];
            trap_old_sum <= trap_old_sum + trap_delay[TRAP_RISE+TRAP_GAP-1] -
                           trap_delay[TRAP_DELAY-1];
            for (trap_index = TRAP_DELAY-1; trap_index > 0; trap_index = trap_index - 1)
                trap_delay[trap_index] <= trap_delay[trap_index-1];
            trap_delay[0] <= trap_input;

            // Clearing must take priority over acquisition.  Previously the
            // live-sample increment later in this clocked block overwrote the
            // zero assigned here, so elapsed time could never be reset.
            if (clear_stats) begin
                state             <= ST_IDLE;
                peak              <= 12'd0;
                area              <= 22'd0;
                pulse_length      <= 10'd0;
                quiet_count       <= 3'd0;
                recovery_count    <= 14'd0;
                pulse_saturated   <= 1'b0;
                trigger_pending   <= 1'b0;
                pending_amplitude <= 12'd0;
                pending_saturated <= 1'b0;
                trap_recent_sum <= 18'sd0;
                trap_old_sum <= 18'sd0;
                trap_saturation_history <= 40'd0;
                for (trap_index = 0; trap_index < TRAP_DELAY; trap_index = trap_index + 1)
                    trap_delay[trap_index] <= 13'sd0;
                adc_min         <= 12'hfff;
                adc_max         <= 12'h000;
                last_peak       <= 12'd0;
                last_energy     <= 12'd0;
                trigger_count   <= 32'd0;
                accepted_count  <= 32'd0;
                rejected_count  <= 32'd0;
                saturated_count <= 32'd0;
                live_samples    <= 64'd0;
            end else if (!enable) begin
                state           <= ST_IDLE;
                peak            <= 12'd0;
                area            <= 22'd0;
                pulse_length    <= 10'd0;
                quiet_count     <= 3'd0;
                recovery_count  <= 14'd0;
                pulse_saturated <= 1'b0;
                trigger_pending <= 1'b0;
                pending_amplitude <= 12'd0;
                pending_saturated <= 1'b0;
            end else begin
                live_samples <= live_samples + 1'b1;
                if (sample < adc_min)
                    adc_min <= sample;
                if (sample > adc_max)
                    adc_max <= sample;

                case (state)
                    ST_IDLE: begin
                        peak            <= 12'd0;
                        area            <= 22'd0;
                        pulse_length    <= 10'd0;
                        quiet_count     <= 3'd0;
                        pulse_saturated <= 1'b0;

                        if (trigger_metric >= threshold) begin
                            if (trigger_pending) begin
                                peak              <= trigger_peak;
                                area              <= {10'd0, pending_amplitude} +
                                                     {10'd0, amplitude};
                                pulse_length      <= 10'd2;
                                pulse_saturated   <= pending_saturated || saturation_for_mode;
                                trigger_pending   <= 1'b0;
                                pending_amplitude <= 12'd0;
                                pending_saturated <= 1'b0;
                                trigger_count     <= trigger_count + 1'b1;
                                trigger_pulse     <= 1'b1;
                                state             <= ST_TRACK;
                            end else begin
                                trigger_pending   <= 1'b1;
                                pending_amplitude <= measured_energy;
                                pending_saturated <= saturation_for_mode;
                            end
                        end else if (opposite_amplitude < threshold) begin
                            trigger_pending   <= 1'b0;
                            pending_amplitude <= 12'd0;
                            pending_saturated <= 1'b0;
                            // Track the baseline only while the sample is
                            // close to it in both directions.  A large
                            // opposite-polarity overshoot used to drag the
                            // baseline to a rail and create thousands of
                            // false retriggers after one clipped pulse.
                            baseline_acc <= baseline_acc + baseline_step;
                        end else begin
                            trigger_pending   <= 1'b0;
                            pending_amplitude <= 12'd0;
                            pending_saturated <= 1'b0;
                        end
                    end

                    ST_TRACK: begin
                        peak            <= peak_candidate;
                        area            <= area_candidate;
                        pulse_saturated <= saturation_now;
                        pulse_length    <= pulse_length + 1'b1;

                        if ((energy_mode != 3'd0) && !trapezoid_mode) begin
                            // Area mode always integrates exactly 64 samples.
                            // Ending the sum as soon as the signal crosses the
                            // release threshold quantises energy by pulse width
                            // and produces a comb-like spectrum.
                            if (pulse_length == AREA_GATE_SAMPLES - 1'b1) begin
                                last_peak <= peak_candidate;
                                if (saturation_now) begin
                                    rejected_count  <= rejected_count + 1'b1;
                                    saturated_count <= saturated_count + 1'b1;
                                    recovery_count  <= SAT_RECOVERY_SAMPLES;
                                end else if ((amplitude > release_level) ||
                                             (quiet_count != 3'd3)) begin
                                    // The waveform has not returned to its
                                    // baseline by 6.4 us, so it is a drift or
                                    // overload rather than the expected pulse.
                                    rejected_count <= rejected_count + 1'b1;
                                    recovery_count <= SAT_RECOVERY_SAMPLES;
                                end else begin
                                    event_bin      <= energy_candidate;
                                    last_energy    <= energy_candidate;
                                    event_valid    <= 1'b1;
                                    accepted_count <= accepted_count + 1'b1;
                                    recovery_count <= NORMAL_RECOVERY_SAMPLES;
                                end
                                quiet_count <= 3'd0;
                                state <= ST_RECOVER;
                            end else if (amplitude <= release_level) begin
                                if (quiet_count != 3'd3)
                                    quiet_count <= quiet_count + 1'b1;
                            end else begin
                                quiet_count <= 3'd0;
                            end
                        end else if (pulse_length == MAX_PULSE_SAMPLES) begin
                            // Peak-height mode keeps the release-based event
                            // boundary used by the stable firmware.
                            rejected_count <= rejected_count + 1'b1;
                            if (saturation_now) begin
                                saturated_count <= saturated_count + 1'b1;
                                recovery_count  <= SAT_RECOVERY_SAMPLES;
                            end else begin
                                recovery_count <= NORMAL_RECOVERY_SAMPLES;
                            end
                            state <= ST_RECOVER;
                        end else if (trigger_metric <= release_level) begin
                            if (quiet_count == 3'd3) begin
                                last_peak <= peak_candidate;
                                if (saturation_now) begin
                                    rejected_count <= rejected_count + 1'b1;
                                    saturated_count <= saturated_count + 1'b1;
                                    recovery_count <= SAT_RECOVERY_SAMPLES;
                                end else begin
                                    event_bin      <= energy_candidate;
                                    last_energy    <= energy_candidate;
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
