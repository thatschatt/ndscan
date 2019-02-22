import numpy
from oitg import uncertainty_to_string
import pyqtgraph
from quamash import QtCore
from typing import Dict, Union
from ..default_analysis import FIT_OBJECTS
from .model import AnnotationDataSource


class AnnotationItem:
    def remove(self) -> None:
        """Remove any pyqtgraph graphics items from target plot and stop listening to
        changes."""
        raise NotImplementedError


class ComputedCurveItem(AnnotationItem):
    @staticmethod
    def is_function_supported(function_name: str) -> bool:
        return function_name in FIT_OBJECTS

    def __init__(self, function_name: str,
                 data_sources: Dict[str, AnnotationDataSource], plot, curve_item):
        self._function = FIT_OBJECTS[function_name].fitting_function
        self._data_sources = data_sources
        self._plot = plot
        self._curve_item = curve_item
        self._curve_item_added = False

        self.redraw_limiter = pyqtgraph.SignalProxy(
            self._plot.getViewBox().sigXRangeChanged, slot=self._redraw, rateLimit=30)

        for source in self._data_sources.values():
            source.changed.connect(self.redraw_limiter.signalReceived)

    def remove(self):
        for source in self._data_sources.values():
            source.changed.disconnect(self.redraw_limiter.signalReceived)
        if self._curve_item_added:
            self._plot.removeItem(self._curve_item)

    def _redraw(self, *args):
        params = {}
        for name, source in self._data_sources.items():
            value = source.get()
            if value is None:
                # Don't have enough data yet.
                # TODO: Use exception instead of None for cleanliness?
                return
            params[name] = value

        if not self._curve_item_added:
            # Ignore bounding box of newly added line for auto-range computation, as we
            # choose its range based on the visible area.
            self._plot.addItem(self._curve_item, ignoreBounds=True)
            self._curve_item_added = True

        # Choose horizontal range based on currently visible area.
        view_box = self._plot.getViewBox()
        x_range, _ = view_box.state["viewRange"]
        ext = (x_range[1] - x_range[0]) / 10
        x_lims = (x_range[0] - ext, x_range[1] + ext)

        # Choose number of points based on width of plot on screen (in pixels).
        fn_xs = numpy.linspace(*x_lims, view_box.width())

        fn_ys = self._function(fn_xs, params)
        self._curve_item.setData(fn_xs, fn_ys)


class CurveItem(AnnotationItem):
    def __init__(self, x_source: AnnotationDataSource, y_source: AnnotationDataSource,
                 plot, curve_item):
        self._x_source = x_source
        self._y_source = y_source
        self._plot = plot
        self._curve_item = curve_item
        self._curve_item_added = False

        for source in [self._x_source, self.y_source]:
            source.changed.connect(self._redraw)

    def remove(self):
        for source in [self._x_source, self.y_source]:
            source.changed.disconnect(self._redraw)
        if self._curve_item_added:
            self._plot.removeItem(self._curve_item)

    def _redraw(self):
        xs = self._x_source.get()
        ys = self._y_source.get()
        if not xs or not ys or len(xs) != len(ys):
            return

        if not self._curve_item_added:
            self._plot.addItem(self._curve_item)
            self._curve_item_added = True
        self._curve_item.setData(xs, ys)


class VLineItem(AnnotationItem):
    """Vertical line marking a given x coordinate, with optional confidence interval."""

    def __init__(self, position_source: AnnotationDataSource,
                 uncertainty_source: Union[None, AnnotationDataSource], plot,
                 base_color, x_data_to_display_scale, x_unit_suffix):
        self._position_source = position_source
        self._uncertainty_source = uncertainty_source
        self._plot = plot
        self._x_data_to_display_scale = x_data_to_display_scale
        self._x_unit_suffix = x_unit_suffix
        self._added_to_plot = False

        self._left_line = pyqtgraph.InfiniteLine(
            movable=False,
            angle=90,
            pen={
                "color": base_color,
                "style": QtCore.Qt.DotLine
            })
        self._center_line = pyqtgraph.InfiniteLine(
            movable=False,
            angle=90,
            label="",
            labelOpts={
                "position": 0.97,
                "color": base_color,
                "movable": True
            },
            pen={
                "color": base_color,
                "style": QtCore.Qt.SolidLine
            })
        self._right_line = pyqtgraph.InfiniteLine(
            movable=False,
            angle=90,
            pen={
                "color": base_color,
                "style": QtCore.Qt.DotLine
            })

        self._position_source.changed.connect(self._redraw)
        if self._uncertainty_source:
            self._uncertainty_source.changed.connect(self._redraw)

    def remove(self):
        self._position_source.changed.disconnect(self._redraw)
        if self._uncertainty_source:
            self._uncertainty_source.changed.disconnect(self._redraw)
        if self._added_to_plot:
            for l in (self._left_line, self._center_line, self._right_line):
                self._plot.removeItem(l)

    def _redraw(self):
        x = self._position_source.get()
        if x is None:
            return

        if not self._added_to_plot:
            self._plot.addItem(self._left_line, ignoreBounds=True)
            self._plot.addItem(self._center_line, ignoreBounds=True)
            self._plot.addItem(self._right_line, ignoreBounds=True)
            self._added_to_plot = True

        delta_x = None
        if self._uncertainty_source:
            delta_x = self._uncertainty_source.get()

        if delta_x is None or numpy.isnan(delta_x) or delta_x == 0.0:
            # If the covariance extraction failed, just don't display the
            # confidence interval at all.
            delta_x = 0.0
            label = str(x)
        else:
            label = uncertainty_to_string(x * self._x_data_to_display_scale,
                                          delta_x * self._x_data_to_display_scale)
        self._center_line.label.setFormat(label + self._x_unit_suffix)

        self._left_line.setPos(x - delta_x)
        self._center_line.setPos(x)
        self._right_line.setPos(x + delta_x)
