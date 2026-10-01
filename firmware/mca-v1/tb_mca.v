`timescale 1ns/1ps

module tb_mca;
    reg clk = 1'b0;
    reg [11:0] adc_data = 12'd2048;
    reg uart_rx_pin = 1'b1;
    wire uart_tx_pin;
    wire adc_pd;
    wire status_led;
    wire trig_out;

    top dut (
        .clk_10mhz(clk),
        .adc_data(adc_data),
        .uart_rx_pin(uart_rx_pin),
        .uart_tx_pin(uart_tx_pin),
        .adc_pd(adc_pd),
        .status_led(status_led),
        .trig_out(trig_out)
    );

    always #50 clk = ~clk; // 10 MHz

    task hold_sample;
        input [11:0] value;
        input integer cycles;
        integer i;
        begin
            for (i = 0; i < cycles; i = i + 1) begin
                @(negedge clk);
                adc_data <= value;
            end
        end
    endtask

    initial begin
        wait(dut.hist_ready === 1'b1);
        hold_sample(12'd2048, 64);

        if (dut.threshold != 12'd32)
            $fatal(1, "unexpected default threshold %0d", dut.threshold);
        if (dut.polarity != 1'b1)
            $fatal(1, "negative-going pulse polarity is not the default");
        if (dut.energy_mode != 3'd0)
            $fatal(1, "peak-height mode is not the default");

        // A large opposite-polarity excursion must not move the baseline or
        // create a trigger.
        hold_sample(12'd4095, 100);
        hold_sample(12'd2048, 16);
        if (dut.baseline != 12'd2048)
            $fatal(1, "opposite excursion moved baseline to %0d", dut.baseline);
        if (dut.trigger_count != 32'd0)
            $fatal(1, "opposite excursion caused a trigger");

        // A one-sample, 80-code negative excursion is below threshold after
        // the four-sample boxcar filter and must not create a false event.
        hold_sample(12'd1968, 1);
        hold_sample(12'd2048, 16);
        if (dut.trigger_count != 32'd0)
            $fatal(1, "single-sample noise excursion caused a trigger");

        // A valid negative-going pulse with peak amplitude 952.
        hold_sample(12'd1696, 3);
        hold_sample(12'd1096, 12);
        hold_sample(12'd1596, 3);
        hold_sample(12'd2048, 24);
        wait(dut.accepted_count == 32'd1);
        hold_sample(12'd2048, 8);

        if (dut.last_peak < 12'd950 || dut.last_peak > 12'd952)
            $fatal(1, "unexpected peak %0d", dut.last_peak);
        if (dut.last_energy < 12'd950 || dut.last_energy > 12'd952)
            $fatal(1, "unexpected peak-mode energy %0d", dut.last_energy);
        if ((dut.spectrum.memory[950] + dut.spectrum.memory[951] +
             dut.spectrum.memory[952]) != 32'd1)
            $fatal(1, "filtered peak histogram bin was not incremented");

        // A rail hit must be rejected and counted as saturated.
        hold_sample(12'd0, 12);
        hold_sample(12'd2048, 24);
        wait(dut.saturated_count == 32'd1);

        if (dut.accepted_count != 32'd1)
            $fatal(1, "saturated pulse was incorrectly accepted");
        if (dut.rejected_count != 32'd1)
            $fatal(1, "saturated pulse was not rejected");
        if (adc_pd !== 1'b0)
            $fatal(1, "ADC power-down output is not low");

        // Regression check: clear_stats must really reset elapsed samples.
        force dut.clear_stats_request = 1'b1;
        @(posedge clk);
        #1;
        release dut.clear_stats_request;
        @(posedge clk);
        #1;
        if (dut.live_samples > 64'd1)
            $fatal(1, "live_samples did not clear: %0d", dut.live_samples);
        if (dut.accepted_count != 32'd0 || dut.rejected_count != 32'd0)
            $fatal(1, "event counters did not clear");

        // The same shaped pulse in area/4 mode integrates the complete
        // baseline-subtracted waveform.  This is a real multi-sample energy
        // estimator rather than a cosmetic x-axis scale.
        force dut.energy_mode = 3'd3;
        hold_sample(12'd1696, 3);
        hold_sample(12'd1096, 12);
        hold_sample(12'd1596, 3);
        hold_sample(12'd2048, 24);
        wait(dut.accepted_count == 32'd1);
        hold_sample(12'd2048, 8);

        if (dut.last_peak < 12'd950 || dut.last_peak > 12'd952)
            $fatal(1, "area mode changed raw peak to %0d", dut.last_peak);
        if (dut.last_energy < 12'd3448 || dut.last_energy > 12'd3462)
            $fatal(1, "unexpected area/4 energy %0d", dut.last_energy);
        if (dut.spectrum.memory[dut.last_energy] != 32'd1)
            $fatal(1, "filtered area histogram bin was not incremented");
        release dut.energy_mode;

        // Unscaled area exceeds 12 bits for this pulse.  It must saturate into
        // bin 4095, never wrap back into the low-energy spectrum.
        force dut.energy_mode = 3'd1;
        hold_sample(12'd1696, 3);
        hold_sample(12'd1096, 12);
        hold_sample(12'd1596, 3);
        hold_sample(12'd2048, 24);
        wait(dut.accepted_count == 32'd2);
        hold_sample(12'd2048, 8);

        if (dut.last_energy != 12'd4095)
            $fatal(1, "over-range area wrapped to %0d", dut.last_energy);
        if (dut.spectrum.memory[4095] != 32'd1)
            $fatal(1, "saturated area did not increment bin 4095");
        release dut.energy_mode;

        // Long low-level baseline excursions are not detector pulses.  They
        // used to integrate to a large or saturated channel; area modes now
        // reject them after the excursion has ended.
        force dut.clear_stats_request = 1'b1;
        @(posedge clk);
        #1;
        release dut.clear_stats_request;
        force dut.energy_mode = 3'd3;
        hold_sample(12'd1968, 200);
        hold_sample(12'd2048, 24);
        wait(dut.rejected_count == 32'd1);
        if (dut.accepted_count != 32'd0)
            $fatal(1, "long baseline excursion was accepted as an event");
        release dut.energy_mode;

        // A sustained low-energy pulse must survive the filter without a
        // significant peak-height error.  This is the intended Am-241 path.
        force dut.clear_stats_request = 1'b1;
        @(posedge clk);
        #1;
        release dut.clear_stats_request;
        hold_sample(12'd1968, 12); // negative amplitude 80
        hold_sample(12'd2048, 24);
        wait(dut.accepted_count == 32'd1);
        if (dut.last_peak < 12'd78 || dut.last_peak > 12'd82)
            $fatal(1, "low-energy pulse peak changed to %0d", dut.last_peak);

        // The trapezoidal shaper must coherently sum the same low-energy
        // pulse into a much larger channel while still producing one event.
        force dut.clear_stats_request = 1'b1;
        @(posedge clk);
        #1;
        release dut.clear_stats_request;
        force dut.energy_mode = 3'd5;
        hold_sample(12'd1968, 20); // negative amplitude 80 for 2 us
        hold_sample(12'd2048, 80);
        wait(dut.accepted_count == 32'd1);
        if (dut.last_energy < 12'd250 || dut.last_energy > 12'd350)
            $fatal(1, "unexpected trapezoid energy %0d", dut.last_energy);
        if (dut.rejected_count != 32'd0)
            $fatal(1, "valid trapezoid pulse was rejected");
        release dut.energy_mode;

        $display("PASS: MCA filter, fixed-window area, trapezoid shaping, width rejection, clamp, saturation, defaults, and clear paths");
        $finish;
    end

    initial begin
        #2000000;
        $fatal(1, "simulation timeout");
    end
endmodule
