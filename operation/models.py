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
    lines = models.JSONField(default=list)  # shipping lines calling here; empty = every line of the port
    active = models.BooleanField(default=True)  # never deleted; a turned-off terminal takes no new visit
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self):
        return self.name

    def history_port(self):
        return self.port


class ListedVessel(models.Model):
    """The vessel list: a vessel's fixed LOA, shared by all ports. Picking a name in the visit dialog fills its LOA;
    visits keep their own copy (name and LOA as text), so editing or deleting an entry never changes a visit."""

    name = models.CharField(max_length=100)  # upper-case, unique ignoring case (validators.clean_listed_vessel)
    loa = models.DecimalField(max_digits=5, decimal_places=1)  # metres
    line = models.CharField(max_length=100, blank=True)  # the operator, from any port's Shipping line list

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


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


class BerthingWindow(models.Model):
    """A line's weekly berthing window at a terminal: start day + time to end day + time (Cairo, Mon = 0); the end
    may be in the next week (Sat 20:00 to Mon 06:00). A line may have several at a terminal, or none."""

    terminal = models.ForeignKey(Terminal, on_delete=models.PROTECT, related_name="windows")
    line = models.CharField(max_length=100)  # from the terminal's shipping lines
    start_day = models.PositiveSmallIntegerField()  # 0 = Monday … 6 = Sunday
    start_time = models.TimeField()
    end_day = models.PositiveSmallIntegerField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["terminal__position", "line", "start_day", "start_time", "id"]

    def __str__(self):
        return f"{self.line} ({self.terminal_id})"

    def history_port(self):
        return Terminal._base_manager.filter(pk=self.terminal_id).values_list("port", flat=True).first() or ""
