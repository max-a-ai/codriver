# Monitoring

This is the control tab. Status tells you something is wrong; this is where you
do something about it.

The three buttons on each sensor row are start, stop and visualise. They are
disabled on purpose: the panel can read a sensor's rate, but it has no
per-sensor driver control yet and nothing to render a single topic into. The
row is here so the layout is settled before the wiring exists.

The lower half is where RViz or Foxglove will be embedded. Until then the
visualiser opens in its own window; the start button below the heading is the
same RViz process the recorder competes with, so it will not start while a
recording is running.

Pick which source you want under the burger menu, in Display.

TODO: wire the per-sensor buttons once the car exposes per-sensor launch files.
