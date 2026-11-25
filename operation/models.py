"""Terminals (each in one port) and the vessel visits at them. Figures (status, hours, moves/hr) are worked out on
read in figures.py, never stored."""

from django.db import models


class Terminal(models.Model):
    name = models.CharField(max_length=40)  # unique ignoring case (validators.clean_terminal)
    code = models.CharField(max_length=10)
    port = models.CharField(max_length=20, db_index=True)  # a Port key
    quay_length = models.PositiveIntegerField()  # metres
    cranes = models.PositiveSmallIntegerField()  # gantry cranes
    berths = models.JSONField(default=list)  # berth names, e.g. ["40/1", "40/2"]
    active = models.BooleanField(default=True)  # never deleted; a turned-off terminal takes no new visit
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self):
        return self.name

    def history_port(self):
        return self.port


class Visit(models.Model):
    """One vessel call at a terminal. The Visit ID is the id."""

    terminal = models.ForeignKey(Terminal, on_delete=models.PROTECT, related_name="visits")
    vessel_name = models.CharField(max_length=100)
    shipping_line = models.CharField(max_length=100)  # from the Master data "line" list
    loa = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)  # metres
    eta = models.DateTimeField()
    ata = models.DateTimeField(null=True, blank=True)
    etb = models.DateTimeField(null=True, blank=True)
    etc = models.DateTimeField(null=True, blank=True)
    atb = models.DateTimeField(null=True, blank=True)
    atd = models.DateTimeField(null=True, blank=True)
    planned_berth = models.CharField(max_length=10, blank=True)
    actual_berth = models.CharField(max_length=10, blank=True)
    cranes = models.PositiveSmallIntegerField(null=True, blank=True)
    discharge = models.PositiveIntegerField(null=True, blank=True)  # moves
    loading = models.PositiveIntegerField(null=True, blank=True)  # moves
    version = models.PositiveIntegerField(default=1)  # edit conflicts (sheet.conflicts)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-eta", "-id"]

    def __str__(self):
        return f"{self.vessel_name} ({self.terminal_id})"

    def history_port(self):
        return Terminal._base_manager.filter(pk=self.terminal_id).values_list("port", flat=True).first() or ""
