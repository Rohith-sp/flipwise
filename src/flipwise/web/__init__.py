"""Live web dashboard: a demonstration layer over the simulator.

Nothing here changes a scheduling rule. The dashboard drives the unchanged `Simulator` and
policies, paced to a demo clock, and reads saved result files for the tables. Standard library
only (PRD §12.1): `http.server` for the server, plain HTML/CSS/JS for the page.
"""
