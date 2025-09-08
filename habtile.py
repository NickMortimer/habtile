"""
Bfrom qgis.PyQt.QtCore import QVariant, QDateTime, Qt
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QInputDialog, QFileDialog, QDialoghic Habitat Classification Tool for QGIS
Creates 256x256 pixel habitat classification boxes with YOLO export capability
"""
from qgis.core import QgsMessageLog
from qgis.PyQt.QtCore import QVariant, QDateTime, Qt
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QInputDialog, QFileDialog, QDialog
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY, QgsRectangle, QgsCoordinateReferenceSystem,
    QgsMapLayer, QgsWkbTypes, QgsEditorWidgetSetup, QgsCoordinateTransform,
    QgsApplication, QgsRasterFileWriter, QgsProcessingFeedback,
    QgsCategorizedSymbolRenderer, QgsSymbol, QgsRendererCategory, QgsSimpleFillSymbolLayer,
    QgsFillSymbol, QgsRandomColorRamp
)
from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
import processing
from qgis.gui import QgsMapTool
from qgis.utils import iface
from qgis.core import Qgis
import os
import csv
from datetime import datetime
def log_debug(msg):
    QgsMessageLog.logMessage(str(msg), tag="HabTile", level=Qgis.Info)

class HabTile(QgsMapTool):
    """Custom map tool for habitat classification"""
    
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.habitat_layer = None
        self.habitat_types_layer = None
        self.last_habitat_main_1 = None
        self.last_habitat_main_2 = None
        self.last_habitat_main_3 = None
        self.last_habitat_main_4 = None
        self.last_habitat_second = None
        self.box_size_pixel = 256
        self.output_dir = QgsProject.instance().homePath()  # Default output directory
        self.last_confidence = 'High'  # Default initial confidence
        self.habitat_types = [
                "Seagrass_High-density strappy ", 
                "Seagrass_Medium-density strappy", 
                "Seagrass_low-density strappy",
                "Sand",
                "Sand patches_large ",
                "Sand patches_small ",
                "Coral_High-density",
                "Coral_Medium-density",
                "Coral_low-density",
                "Coral rubble",
                "Coral heads",
                "Rocky shoreline",
                "Sandy shoreline",
                "Trees on land",
                "Mangroves",
                "Macroalgae: calcified",
                "Deep water",
                "",

        ]
        self.color_types=["#08F704",
                          "#37FF8E",
                          "#7FFEB6",
                          "#FCF803",
                          "#F9F66B",
                          "#FBFAC6",
                          "#F41A02",
                          "#F56150",
                          "#F57E71",
                          "#F7B3AD",
                          "#FEE1DE",
                          "#E36C11",
                          "#ECBF5F",                          
                          "#1E5200",
                          "#318600",
                          "#6E4541",
                          "#01081D",
                          "#6E4541",
                          ]
        self.setup_habitat_layer()
    
    def setup_habitat_layer(self):
        """Create or get the habitat classification layer"""
        # Check if habitat layer already exists
        from qgis.core import QgsField
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == "Habitat_Classifications":
                field_name = "box_size_pixel"
                if field_name not in [f.name() for f in layer.fields()]:
                    layer.startEditing()
                    from qgis.core import QgsField
                    layer.addAttribute(QgsField(field_name, QVariant.Int))
                    layer.updateFields()
                    layer.commitChanges()
                self.habitat_layer = layer
                return
        self.add_habitat_types(self.habitat_types, self.color_types)
        # Create new habitat layer
        pixel_size, raster_name, raster_crs = self.get_selected_raster_info()
        layer_path = f"Polygon?crs={raster_crs}"  # Adjust CRS as needed
        self.habitat_layer = QgsVectorLayer(layer_path, "Habitat_Classifications", "memory")
        
        # Add fields
        fields = [
            QgsField("habitat_1", QVariant.String, len=40),
            QgsField("habitat_2", QVariant.String, len=40),
            QgsField("habitat_3", QVariant.String, len=40),
            QgsField("habitat_4", QVariant.String, len=40),
            QgsField("notes", QVariant.String, len=255),
            QgsField("source_raster", QVariant.String, len=100),
            QgsField("pixel_size", QVariant.Double),
            QgsField("tile_id", QVariant.String, len=100),
            QgsField("box_size_m", QVariant.Double),
            QgsField("box_size_pixel", QVariant.Int),
            QgsField("center_x", QVariant.Double),
            QgsField("center_y", QVariant.Double)
        ]
        
        self.habitat_layer.dataProvider().addAttributes(fields)
        self.habitat_layer.updateFields()
        # Set fields to invisible
        # for field in self.habitat_layer.fields():
        #     name = field.name()
        #     if name not in ["habitat", "notes"]:
        #         index = self.habitat_layer.fields().indexFromName(name)
        #         self.habitat_layer.setEditorWidgetSetup(index, QgsEditorWidgetSetup('Hidden', {}))
        
        # Configure attribute form
        self.configure_attribute_form()
        
        # Setup the categorized renderer
        categories = []
        # Build a dict mapping habitat name to color
        color_map = {feat['habitat_name']: feat['cat_color'] for feat in self.habitat_types_layer.getFeatures()}

        #unique_values = self.habitat_types_layer.uniqueValues(self.habitat_types_layer.fields().indexFromName('habitat_name'))

        for habitat_type,color_hex in zip(self.habitat_types, self.color_types):
            symbol = QgsFillSymbol.createSimple({'color': color_hex})
            for layer in symbol.symbolLayers():
                color = layer.color()
                color.setAlphaF(0.5)
                layer.setColor(color)
            category = QgsRendererCategory(habitat_type, symbol, habitat_type)
            categories.append(category)

        renderer = QgsCategorizedSymbolRenderer('habitat_1', categories)
        self.habitat_layer.setRenderer(renderer)
        # Add to project
        QgsProject.instance().addMapLayer(self.habitat_layer)
        
    def add_habitat_types(self, initial_types=["Coral", "Sand", "Seagrass"],color_types=["#FF6F61","#F4E1B6","#2E8B57"]):
        # 1. Create the in-memory lookup layer
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == "habitat_lookup":
                self.habitat_types_layer = layer
                return
        habitat_types_layer = QgsVectorLayer("None", "habitat_lookup", "memory")
        # Add fields
        fields = [
            QgsField("habitat_name", QVariant.String, len=40),
            QgsField("cat_color", QVariant.String, len=10)
        ]
        
        habitat_types_layer.dataProvider().addAttributes(fields)
        habitat_types_layer.updateFields()

        
        # habitat_types_layer.updateExtents()
        habitat_types_layer.startEditing()
        fields = habitat_types_layer.fields()
        log_debug(f"Fields: {[field.name() for field in fields]}")

        for name, hex_color in zip(initial_types, color_types):
            feat = QgsFeature()
            feat.setFields(fields, True)  # bind fields with init=true
            feat.setAttribute(fields.indexOf("habitat_name"), name)
            feat.setAttribute(fields.indexOf("cat_color"), hex_color)
            habitat_types_layer.addFeature(feat)
        habitat_types_layer.commitChanges()
        # Add the lookup layer to the project so it's usable by ValueRelation
        QgsProject.instance().addMapLayer(habitat_types_layer)
        self.habitat_types_layer = habitat_types_layer

    
    def configure_attribute_form(self):
        """Configure the attribute form for quick habitat selection"""
        form_config = self.habitat_layer.editFormConfig()
        # Set up habitat types with editable combo box
        habitat_config = {
            'Layer': self.habitat_types_layer.id(),
            'Key': 'habitat_name',
            'Value': 'habitat_name',
            'AllowNull': True,
            'AllowMulti': False,
            'AllowAddFeatures': True,
            'UseCompleter': True,
            'OrderByValue': True
        }

        config = {
            'map': {val: val for val in self.habitat_types}  # display → stored
        }

        habitat_setup = QgsEditorWidgetSetup('ValueMap', config)
        size_setup = {'map':{'64x64':64,'128x128':128,'256x256':256}}
        box_setup = QgsEditorWidgetSetup('ValueMap', size_setup)

        for field in ['habitat_1', 'habitat_2', 'habitat_3', 'habitat_4']:
            self.habitat_layer.setEditorWidgetSetup(
                self.habitat_layer.fields().indexFromName(field),
                habitat_setup)
                
        self.habitat_layer.setEditorWidgetSetup(
            self.habitat_layer.fields().indexFromName('box_size_pixel'),
                box_setup)


        # self.habitat_layer.setEditorWidgetSetup(
        #     self.habitat_layer.fields().indexFromName('habitat_second'),
        #     habitat_setup
        # )
        
        # self.habitat_layer.setEditorWidgetSetup(
        #     self.habitat_layer.fields().indexFromName('habitat_main'),
        #     habitat_setup
        # )
        # self.habitat_layer.setEditorWidgetSetup(
        #     self.habitat_layer.fields().indexFromName('habitat_second'),
        #     habitat_setup
        # )
        
        # Set up confidence as dropdown
        confidence_config = {
            'map': [
                {'High': 'High'},
                {'Medium': 'Medium'},
                {'Low': 'Low'}
            ]
        }
        # confidence_setup = QgsEditorWidgetSetup('ValueMap', confidence_config)
        # self.habitat_layer.setEditorWidgetSetup(
        #     self.habitat_layer.fields().indexFromName('confidence'),
        #     confidence_setup
        # )
        
        # Set default value for date_time
        # self.habitat_layer.setDefaultValueExpression(
        #     self.habitat_layer.fields().indexFromName('date_time'),
        #     'now()'
        # )
        
        self.habitat_layer.setEditFormConfig(form_config)
    
    def get_selected_raster_info(self):
        """Get pixel size and name from selected raster layer"""
        layer = iface.activeLayer()
        if layer and layer.type() == QgsMapLayer.RasterLayer:
            pixel_size = layer.rasterUnitsPerPixelX()
            raster_name = layer.name()
            raster_crs = layer.crs()
            return pixel_size, raster_name, raster_crs
        return None, None, None
    
    def canvasPressEvent(self, event):
        """Handle mouse click on canvas"""
        # Get click point in map coordinates
        point = self.toMapCoordinates(event.pos())
        
        # Check if Ctrl key is pressed
        modifiers = event.modifiers()
        is_ctrl_click = bool(modifiers & Qt.ControlModifier)
        
        # Get raster info
        pixel_size, raster_name, raster_crs = self.get_selected_raster_info()
        
        if not pixel_size or not raster_name:
            QMessageBox.warning(
                None, 
                "No Raster Selected", 
                "Please select an automosaic raster layer first."
            )
            return
        
        # Transform point to raster's CRS for accurate size calculation
        transform = QgsCoordinateTransform(
            self.canvas.mapSettings().destinationCrs(),
            raster_crs,
            QgsProject.instance()
        )
        transformed_point = transform.transform(point)
        
        # Calculate 256x256 pixel box size in raster units
        box_size_m = self.box_size_pixel * pixel_size
        half_box = box_size_m / 2
        
        # Create rectangle geometry in raster CRS
        rect = QgsRectangle(
            transformed_point.x() - half_box,
            transformed_point.y() - half_box,
            transformed_point.x() + half_box,
            transformed_point.y() + half_box
        )
        geometry = QgsGeometry.fromRect(rect)
        
        # Transform geometry back to map CRS
        transform_back = QgsCoordinateTransform(
            raster_crs,
            self.canvas.mapSettings().destinationCrs(),
            QgsProject.instance()
        )
        geometry.transform(transform_back)
        
        # Create feature
        feature = QgsFeature()
        feature.setGeometry(geometry)
        
        # Generate tile ID
        tile_id = f"{raster_name}_{int(point.x())}_{int(point.y())}_{datetime.now().strftime('%H%M%S')}"
        fid_idx = self.habitat_layer.fields().indexFromName('fid')

        attrs = {
            "habitat_1": self.last_habitat_main_1,
            "habitat_2": self.last_habitat_main_2,
            "habitat_3": self.last_habitat_main_3,
            "habitat_4": self.last_habitat_main_4,
            "notes": "",
            "source_raster": raster_name,
            "pixel_size": pixel_size,
            "tile_id": tile_id,
            "box_size_m": box_size_m,
            "box_size_pixel": self.box_size_pixel,
            "center_x": point.x(),
            "center_y": point.y(),
        }

        # Apply attributes to feature
        feature.setAttributes([None] * len(self.habitat_layer.fields()))  # init with correct length
        for field_name, value in attrs.items():
            idx = self.habitat_layer.fields().indexFromName(field_name)
            if idx != -1:
                feature.setAttribute(idx, value)
        

            # Start editing
        self.habitat_layer.startEditing()

        if is_ctrl_click and self.last_habitat_main_1:
            # Quick add using last values without showing form
            self.habitat_layer.addFeature(feature)
            self.habitat_layer.commitChanges()
            self.canvas.refresh()
        else:
            # Add feature and show form
            self.habitat_layer.addFeature(feature)
            
            # Create and configure the feature form

            # List of fields you want on the form
            allowed_fields = [
                "habitat_1",
                "habitat_2",
                "habitat_3",
                "habitat_4",
                "notes",
                "source_raster",
                "pixel_size",
                "tile_id",
                "box_size_m",
                "box_size_pixel",
                "center_x",
                "center_y"
            ]

            for idx, field in enumerate(self.habitat_layer.fields()):
                if field.name() in allowed_fields:
                    continue
                # Hide all other fields
                self.habitat_layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("Hidden", {}))
            dialog = iface.getFeatureForm(self.habitat_layer, feature)
            
            # Connect to form response
            if dialog.exec_() == QDialog.Accepted:
                # Get the updated feature
                saved_feature = self.habitat_layer.getFeature(feature.id())
                
                # Update last used values
                self.last_habitat_main_1 = saved_feature["habitat_1"]
                self.last_habitat_main_2 = saved_feature["habitat_2"]
                self.last_habitat_main_3 = saved_feature["habitat_3"]
                self.last_habitat_main_4 = saved_feature["habitat_4"]
                if (self.box_size_pixel != saved_feature["box_size_pixel"]):
                    self.box_size_pixel = saved_feature["box_size_pixel"]
                    # Calculate 256x256 pixel box size in raster units
                    box_size_m = self.box_size_pixel * pixel_size
                    half_box = box_size_m / 2
                    
                    # Create rectangle geometry in raster CRS
                    rect = QgsRectangle(
                        transformed_point.x() - half_box,
                        transformed_point.y() - half_box,
                        transformed_point.x() + half_box,
                        transformed_point.y() + half_box
                    )
                    geometry = QgsGeometry.fromRect(rect)
                    
                    # Transform geometry back to map CRS
                    transform_back = QgsCoordinateTransform(
                        raster_crs,
                        self.canvas.mapSettings().destinationCrs(),
                        QgsProject.instance()
                    )
                    geometry.transform(transform_back)
                    saved_feature.setGeometry(geometry)
                        # Update the feature in the layer
                    self.habitat_layer.startEditing()
                    self.habitat_layer.updateFeature(saved_feature)
                    # # If new habitat types were entered, add them to the list
                # if saved_feature["habitat"] and saved_feature["habitat"] not in self.habitat_types:
                #     self.habitat_types.append(saved_feature["habitat"])
                #     self.configure_attribute_form()  # Refresh the form configuration
                
                
                self.habitat_layer.commitChanges()
            else:
                # Form was cancelled, roll back the changes
                self.habitat_layer.rollBack()
            
            self.canvas.refresh()
        self.canvas.refresh()
        

class HabitatClassificationPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.menu = '&HabTile'  # menu name used when adding actions
        self.tool = None
        self.toolbar_button = None  # track toolbar widget so it can be removed on unload

    def initGui(self):
        """Create action(s) and add to toolbar/menu"""
        icon = QIcon(':/plugins/habtile/icon.png')  # adjust path if needed
        action = QAction(icon, "HabTile", self.iface.mainWindow())
        action.setObjectName('habtile_action')
        action.setToolTip('HabTile — create 256x256 habitat classification tiles')
        action.triggered.connect(self.run)  # your existing run method

        # Add the QAction to QGIS toolbar and menu (keeps expected behaviour)
        self.iface.addToolBarIcon(action)
        self.iface.addPluginToMenu(self.menu, action)

        # Also create a QToolButton so the toolbar can show text with the icon
        try:
            from qgis.PyQt.QtWidgets import QToolButton
            button = QToolButton(self.iface.mainWindow())
            button.setDefaultAction(action)
            # change style to show text (choose TextBesideIcon or TextUnderIcon)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setObjectName('habtile_toolbutton')
            self.iface.addToolBarWidget(button)
            self.toolbar_button = button
        except Exception:
            # fallback: no toolbar widget created
            self.toolbar_button = None

        # track the action so unload() can remove it
        if action not in self.actions:
            self.actions.append(action)

        # Register the processing provider so the algorithm shows in the Processing toolbox
        self.processing_provider = HabitatProcessingProvider(self)
        QgsApplication.processingRegistry().addProvider(self.processing_provider)

    def unload(self):
        """Remove plugin menu items, toolbar icons and deactivate tool"""
        # If our map tool is active, unset it
        try:
            canvas = self.iface.mapCanvas()
            if self.tool and canvas.mapTool() == self.tool:
                canvas.unsetMapTool(self.tool)
        except Exception:
            pass

        # Remove actions from menu and toolbar
        for action in list(self.actions):
            try:
                self.iface.removePluginMenu(self.menu, action)
            except Exception:
                pass
            try:
                self.iface.removeToolBarIcon(action)
            except Exception:
                pass

        # remove the added tool button (if we created one)
        if getattr(self, 'toolbar_button', None):
            try:
                self.iface.removeToolBarWidget(self.toolbar_button)
            except Exception:
                try:
                    parent = self.iface.mainWindow()
                    parent.removeAction(self.toolbar_button.defaultAction())
                except Exception:
                    pass
            self.toolbar_button = None

        # Unregister processing provider
        if getattr(self, 'processing_provider', None):
            QgsApplication.processingRegistry().removeProvider(self.processing_provider)
            self.processing_provider = None

        # clear action list
        self.actions = []

        # if you created any additional widgets (dockwidgets, toolbars), remove/close them here
        # e.g. if hasattr(self, 'dock') and self.dock:
        #           self.iface.removeDockWidget(self.dock)
        #           self.dock = None

    def run_export(self):
        """Run the export dialog"""
        if not self.tool or not self.tool.habitat_layer:
            QMessageBox.warning(
                None,
                "No Data",
                "No habitat classifications available to export."
            )
            return
            
        output_dir = QFileDialog.getExistingDirectory(
            None,
            "Select Output Directory",
            "",
            QFileDialog.ShowDirsOnly
        )
        
        if output_dir:
            try:
                self.tool.export_to_yolo(output_dir)
                QMessageBox.information(
                    None,
                    "Export Complete",
                    f"Dataset exported successfully to:\n{output_dir}"
                )
            except Exception as e:
                QMessageBox.critical(
                    None,
                    "Export Error",
                    f"Failed to export dataset:\n{str(e)}"
                )
    
    def run(self):
        """Run the tool"""
        if not self.tool:
            self.tool = HabTile(iface.mapCanvas())
        
        iface.mapCanvas().setMapTool(self.tool)
        
        QMessageBox.information(
            None,
            "Habitat Classification Tool",
            "Tool activated!\n\n"
            "1. Select your automosaic raster layer\n"
            "2. Click anywhere on the map to create a 256x256 pixel classification box\n"
            "3. Fill in the habitat type and other attributes\n"
            "4. Use Export functions to generate YOLO training data"
        )

from qgis.core import (
    QgsProcessingProvider,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFolderDestination,
    QgsProcessingException,
    QgsApplication,
    QgsProcessingContext,
    QgsProcessingFeedback
)

class ExportToYoloAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    OUTPUT_DIR = 'OUTPUT_DIR'

    def __init__(self, provider=None):
        super().__init__()
        # store provider as a private attribute to avoid shadowing the provider() method
        self._provider = provider

    def name(self):
        return 'export_to_yolo'

    def displayName(self):
        return 'Export habitat classifications to YOLO'

    def group(self):
        return 'HabTile'

    def groupId(self):
        return 'habtile'

    def shortHelpString(self):
        return 'Export habitat layer features and tiles to a YOLO-style dataset directory.'

    def initAlgorithm(self, config=None):
        # optional input layer (if not provided algorithm will try to use the plugin layer)
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                'Habitat vector layer (optional)',
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                'Output directory'
            )
        )

    def createInstance(self):
        # create a new instance with the same provider
        return ExportToYoloAlgorithm(self._provider)

    def provider(self):
        # return the provider instance when requested by the Processing framework
        return self._provider

    def processAlgorithm(self, parameters, context: QgsProcessingContext, feedback: QgsProcessingFeedback):
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        out_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)
        if layer is None:
            raise QgsProcessingException('No habitat layer provided.')
        # You may want to get habitat_types from the plugin or from the layer
        # For now, try to get from plugin if available, else from unique values
        habitat_types = []
        prov = self.provider()
        if prov and getattr(prov, 'plugin', None) and getattr(prov.plugin, 'tool', None):
            habitat_types = prov.plugin.tool.habitat_types
        else:
            # fallback: get unique values from the layer
            idx = layer.fields().indexFromName("habitat_1")
            if idx >= 0:
                habitat_types = list(sorted(set([f["habitat_1"] for f in layer.getFeatures()])))
        export_to_yolo(layer, out_dir)
        return {'OUTPUT': out_dir}

class HabitatProcessingProvider(QgsProcessingProvider):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin

    def id(self):
        return 'habtile'

    def name(self):
        return 'HabTile'

    def loadAlgorithms(self):
        log_debug("HabTile: Registering ExportToYoloAlgorithm")
        self.addAlgorithm(ExportToYoloAlgorithm(self))

    def longName(self):
        return self.name()

def export_to_yolo(layer, output_dir):
    """Export habitat classifications to YOLO format"""
    import os, csv
    if not output_dir:
        raise ValueError("Output directory not specified")
    if not layer or layer.featureCount() == 0:
        raise ValueError("No habitat classifications to export")
    images_dir = os.path.join(output_dir, "images")
    labels_dir = os.path.join(output_dir, "labels")
    metadata_dir = os.path.join(output_dir, "metadata")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)
    class_file = os.path.join(output_dir, "classes.txt")
    habitat_types = set()
    # make habitat list from layer features
    for feature in layer.getFeatures():
        habitat_fields = ["habitat_1", "habitat_2", "habitat_3", "habitat_4"]
        habs = filter(lambda x: 'NULL' not in x, [str(feature[field]).strip() for field in habitat_fields])
        habitat_type = "; ".join(habs)
        log_debug(f"Feature habitats: {habitat_type}")
        if habitat_type:
            habitat_types.add(habitat_type)
        #need an index class_id = habitat_types.index(habitat_type)
    habitat_types = sorted(habitat_types)  # sort for consistent order

    for feature in layer.getFeatures():
        habitat_fields = ["habitat_1", "habitat_2", "habitat_3", "habitat_4"]
        habs = filter(lambda x: 'NULL' not in x, [str(feature[field]).strip() for field in habitat_fields])
        habitat_type = "; ".join(habs)
        
        # if habitat_type is not in habitat_types: add it to the set
        raster_name = feature["source_ras"]
        tile_id = feature["tile_id"]
        bbox = feature.geometry().boundingBox()
        # Find the raster layer
        raster_layer = None
        from qgis.core import QgsMapLayer
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.type() == QgsMapLayer.RasterLayer and lyr.name() == raster_name:
                raster_layer = lyr
                break
        if not raster_layer:
            continue
        image_path = os.path.join(images_dir, f"{tile_id}.jpg")
        label_path = os.path.join(labels_dir, f"{tile_id}.txt")
        metadata_path = os.path.join(metadata_dir, f"{tile_id}.csv")
        extent = raster_layer.extent()
        if not extent.contains(bbox):
            continue
        # Ensure bbox is in raster CRS
        if layer.crs() != raster_layer.crs():
            transform = QgsCoordinateTransform(layer.crs(), raster_layer.crs(), QgsProject.instance())
            bbox = transform.transformBoundingBox(bbox)
        # Prepare PROJWIN as [xmin, ymax, xmax, ymin]
        projwin = [bbox.xMinimum(), bbox.yMaximum(), bbox.xMaximum(), bbox.yMinimum()]
        from osgeo import gdal
        gdal.Translate(
            image_path,
            raster_layer.source(),
            projWin=projwin   # [xmin, ymax, xmax, ymin] in raster CRS units
        )
        class_id = habitat_types.index(habitat_type)
        with open(label_path, 'w') as f:
            f.write(f"{class_id} 0.5 0.5 1.0 1.0\n")
    metadata_path = os.path.join(metadata_dir, f"metadata.csv")
    with open(metadata_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'tile_id', 'habitat_type', 'confidence', 'source_raster',
            'pixel_size', 'box_size_m', 'center_x', 'center_y',
            'observer', 'date_time', 'notes'
        ])
        for feature in layer.getFeatures():
            habitat_fields = ["habitat_1", "habitat_2", "habitat_3", "habitat_4"]
            habs = filter(lambda x: 'NULL' not in x, [str(feature[field]).strip() for field in habitat_fields])
            habitat_type = "; ".join(habs)
            writer.writerow([
                feature["tile_id"], habitat_type, feature["confidence"] if "confidence" in feature.fields().names() else "",
                raster_name, feature["pixel_size"], feature["box_size_m"],
                feature["center_x"], feature["center_y"],
                feature["observer"] if "observer" in feature.fields().names() else "",
                feature["date_time"].toString() if "date_time" in feature.fields().names() else "",
                feature["notes"] if "notes" in feature.fields().names() else ""
            ])
    with open(class_file, 'w') as f:
        f.write('\n'.join(habitat_types))

