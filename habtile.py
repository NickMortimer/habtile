"""
Bfrom qgis.PyQt.QtCore import QVariant, QDateTime, Qt
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QInputDialog, QFileDialog, QDialoghic Habitat Classification Tool for QGIS
Creates 256x256 pixel habitat classification boxes with YOLO export capability
"""
from qgis.core import QgsMessageLog, QgsVectorFileWriter
from qgis.PyQt.QtCore import QVariant, QDateTime, Qt, QTimer
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
from pathlib import Path
import os
import csv
from datetime import datetime
def log_debug(msg):
    QgsMessageLog.logMessage(str(msg), tag="HabTile", level=Qgis.Info)

class HabTile(QgsMapTool):
    """Custom map tool for habitat classification"""
    
    def __init__(self, canvas, habitat_layer=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.habitat_layer = habitat_layer
        self.habitat_types_layer = None
        self.last_habitat_main_1 = None
        self.last_habitat_main_2 = None
        self.last_habitat_main_3 = None
        self.last_habitat_main_4 = None
        self.last_habitat_second = None
        self.box_size_pixel = 256
        self.output_dir = QgsProject.instance().homePath()  # Default output directory
        self.last_confidence = 'High'  # Default initial confidence
        self.habitat_types = []
        self.color_types=[]
        self.habitat_types,self.habitat_colors = self.load_or_create_habitat_types()

        
    
    def setup_habitat_layer(self):
        self.habitat_layer = None
        pixel_size, raster_name, raster_crs,raster_layer = self.get_selected_raster_info()
        if not pixel_size or not raster_name or not raster_crs or not raster_crs.isValid():
            QMessageBox.warning(
                None,
                "No Raster Selected",
                "Please select a valid automosaic raster layer first."
            )
            return
        layer_name = f"Habitat_{raster_name}".lower()
        required_fields = [
            ("habitat_1", QVariant.String, 40),
            ("habitat_2", QVariant.String, 40),
            ("habitat_3", QVariant.String, 40),
            ("habitat_4", QVariant.String, 40),
            ("notes", QVariant.String, 255),
            ("source_raster", QVariant.String, 100),
            ("pixel_size", QVariant.Double, None),
            ("tile_id", QVariant.String, 100),
            ("box_size_m", QVariant.Double, None),
            ("box_size_pixel", QVariant.Int, None),
            ("center_x", QVariant.Double, None),
            ("center_y", QVariant.Double, None)
        ]

        # Try to find an existing layer
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name().startswith(layer_name) and layer.type() == QgsMapLayer.VectorLayer:
                # Add missing fields if needed
                missing = []
                for name, qtype, length in required_fields:
                    if name not in [f.name() for f in layer.fields()]:
                        missing.append((name, qtype, length))
                if missing:
                    layer.startEditing()
                    for name, qtype, length in missing:
                        if length:
                            layer.addAttribute(QgsField(name, qtype, len=length))
                        else:
                            layer.addAttribute(QgsField(name, qtype))
                    layer.updateFields()
                    layer.commitChanges()
                self.habitat_layer = layer
                self.set_symbology()
                self.configure_attribute_form()
                return
        # If habitat layer not found, prompt to create
        reply = QMessageBox.question(
            None,
            "Habitat Layer Missing",
            "The habitat layer has been deleted or removed from the project.\n\n"
            "Would you like to recreate it?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # If not found, create new layer
            layer_path = f"Polygon?crs={raster_crs.authid()}"
            self.habitat_layer = QgsVectorLayer(layer_path, layer_name, "memory")
            fields = []
            for name, qtype, length in required_fields:
                if length:
                    fields.append(QgsField(name, qtype, len=length))
                else:
                    fields.append(QgsField(name, qtype))
            self.habitat_layer.dataProvider().addAttributes(fields)
            self.habitat_layer.updateFields()
            self.habitat_layer.setCrs(QgsCoordinateReferenceSystem(raster_crs))
            self.set_symbology()
            self.configure_attribute_form()
            QgsProject.instance().addMapLayer(self.habitat_layer)
            self.habitat_layer_saved = False
            # restore the raster layer as active after the event loop updates
            def restore_active_layer():
                iface.setActiveLayer(raster_layer)
            QTimer.singleShot(0, restore_active_layer)



    def set_symbology(self):
        # Setup the categorized renderer
        categories = []
        # Build a dict mapping habitat name to color
        for habitat_type,color_hex in zip(self.habitat_types, self.habitat_colors):
            QgsMessageLog.logMessage(f"Categories:  {habitat_type} {color_hex}", level=Qgis.Info)
            symbol = QgsFillSymbol.createSimple({'color': color_hex})
            for layer in symbol.symbolLayers():
                color = layer.color()
                color.setAlphaF(0.5)
                layer.setColor(color)
            category = QgsRendererCategory(habitat_type, symbol, habitat_type)
            categories.append(category)
        ##print out categories to log for debugging
        QgsMessageLog.logMessage(f"Categories: {categories} {self.habitat_types} {self.habitat_colors}", level=Qgis.Info)
        renderer = QgsCategorizedSymbolRenderer('habitat_1', categories)
        self.habitat_layer.setRenderer(renderer)


    def load_or_create_habitat_types(self):
        import os
        from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
        project_dir = QgsProject.instance().homePath()
        default_csv = os.path.join(project_dir, "habitat_types.csv")
        habitat_types = [
                "Seagrass_High-density strappy ", 
                "Seagrass_Medium-density strappy", 
                "Seagrass_low-density strappy",
                "Sand",
                "Sand patches_large ",
                "Sand patches_small ",
                "Coral_ High-density",
                "Coral_Medium-density",
                "Coral-low-density",
                "Coral-rubble",
                "Coral-heads",
                "Rocky-shoreline",
                "Sandy-shoreline",
                "Trees-on-land",
                "Mangroves",
                "Macroalgae-calcified",
                "Deep water",
                "",

        ]
        color_types = ["#08F704",
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

        # Try to load default CSV
        if os.path.exists(default_csv):
            habitat_types = []
            color_types = []
            with open(default_csv, newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    habitat_types.append(row['habitat_name'])
                    color_types.append(row.get('cat_color', '#FFFFFF'))
        else:
            with open(default_csv, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['habitat_name', 'cat_color'])
                for habitat, color in zip(habitat_types, color_types):
                    writer.writerow([habitat, color])
        return habitat_types, color_types
    

    
    def configure_attribute_form(self):
        """Configure the attribute form for quick habitat selection"""
        form_config = self.habitat_layer.editFormConfig()
        config = {
            'map': {val: val for val in self.habitat_types}  # display → stored
        }
        QgsMessageLog.logMessage(f"COMBO: {config} ", level=Qgis.Info)

        habitat_setup = QgsEditorWidgetSetup('ValueMap', config)
        size_setup = {'map':{'64x64':64,'128x128':128,'256x256':256}}
        box_setup = QgsEditorWidgetSetup('ValueMap', size_setup)

        for field in ['habitat_1', 'habitat_2', 'habitat_3', 'habitat_4']:
            self.habitat_layer.setEditorWidgetSetup(
                self.habitat_layer.fields().indexFromName(field),
                habitat_setup
            )
        self.habitat_layer.setEditorWidgetSetup(
            self.habitat_layer.fields().indexFromName('box_size_pixel'),
            box_setup
        )
        self.habitat_layer.setEditFormConfig(form_config)
    
    def get_selected_raster_info(self):
        """Get pixel size and name from selected raster layer"""
        layer = iface.activeLayer()
        if layer and layer.type() == QgsMapLayer.RasterLayer:
            pixel_size = layer.rasterUnitsPerPixelX()
            raster_name = layer.name()
            raster_crs = layer.crs()
            return pixel_size, raster_name, raster_crs, layer
        return None, None, None, None
    

    def suggest_save_path(self,layer):
        """Suggest a filename in the project directory (or home if not saved)."""
        safe_name = layer.name().replace(" ", "_").lower()
        date_tag = datetime.now().strftime("%Y%m%d")
        filename = f"{safe_name}_{date_tag}.gpkg"

        project_file = QgsProject.instance().fileName()
        if project_file:
            default_dir = Path(project_file).parent
        else:
            default_dir = Path.home()

        return default_dir / filename

    def save_scratch_layer_with_dialog(self,layer):
        if not layer.isValid():
            raise ValueError("Layer is not valid")
        """Open a dialog box to save a scratch layer to GeoPackage."""
        default_path = self.suggest_save_path(layer)

        # Open file save dialog with default path filled in
        file_path, _ = QFileDialog.getSaveFileName(
            None,
            "Save Scratch Layer",
            str(default_path),
            "GeoPackage (*.gpkg)"
        )
        if not file_path:  # user cancelled
            return None
        
        if not os.path.isdir(os.path.dirname(file_path)):
            QMessageBox.critical(None, "Save Error", f"Directory does not exist: {os.path.dirname(file_path)}")
            return None
        if not os.access(os.path.dirname(file_path), os.W_OK):
            QMessageBox.critical(None, "Save Error", f"Cannot write to directory: {os.path.dirname(file_path)}")
            return None
        import processing
        params = {
            'INPUT': layer,
            'OUTPUT': file_path,
            #'LAYER_NAME': layer.name(),
            'OVERWRITE': True
        }
        try:
            
            # After saving with processing.run("native:savefeatures", params)
            # Hold the renderer from the memory layer
            renderer = layer.renderer().clone()
            result = processing.run("native:savefeatures", params)



            saved_layer_path = result['OUTPUT']
            # Export symbology to QML
            qml_path = saved_layer_path.replace(".gpkg", ".qml")
            layer.saveNamedStyle(qml_path)


            saved_layer = QgsVectorLayer(saved_layer_path, '', "ogr")
            saved_layer.setRenderer(renderer)
            if saved_layer.isValid():
                saved_layer.setName(layer.name())  # Set to original name
                QgsProject.instance().addMapLayer(saved_layer)
                QgsProject.instance().removeMapLayer(layer.id())
                self.habitat_layer = saved_layer
                self.set_symbology()
                # Save style to GeoPackage
                try:
                    saved_layer.saveNamedStyle(file_path, "gpkg")
                except Exception as e:
                    QgsMessageLog.logMessage(f"Could not save style: {e}", level=Qgis.Warning)
        except Exception as e:
            QMessageBox.critical(None, "Save Error", f"Error saving layer:\n{str(e)}")
            return None
        return file_path




    def canvasPressEvent(self, event):

        """Handle mouse click on canvas"""
        # Get click point in map coordinates
        point = self.toMapCoordinates(event.pos())
        
        # Check if Ctrl key is pressed
        modifiers = event.modifiers()
        is_ctrl_click = bool(modifiers & Qt.ControlModifier)
        pixel_size, raster_name, raster_crs, raster_layer = self.get_selected_raster_info()  
        self.setup_habitat_layer()
        if self.habitat_layer: 
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

                # Add a label showing the layer name at the top of the dialog
                from qgis.PyQt.QtWidgets import QLabel, QVBoxLayout
                layer_label = QLabel(f"Saving to layer: <b>{self.habitat_layer.name()}</b>")
                layout = dialog.layout()
                if layout:
                    layout.addWidget(layer_label, 0, 0)
                
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
                    self.canvas.refresh()
                    if self.habitat_layer.providerType() == "memory" and self.habitat_layer.featureCount() !=0:
                        def save_layer():
                            self.save_scratch_layer_with_dialog(self.habitat_layer)
                            self.habitat_layer_saved = True
                        QTimer.singleShot(0, save_layer)
                else:
                    # Form was cancelled, roll back the changes
                    self.habitat_layer.rollBack()
                self.canvas.refresh()
                
                
            self.canvas.refresh()
        

class HabitatClassificationPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.menu = '&HabTile'
        self.tool = None
        self.selected_habitat_layer = None  # Store selected layer if tool not yet created
        self.toolbar_button = None

    def initGui(self):
        """Create action(s) and add to toolbar/menu"""
        icon = QIcon(':/plugins/habtile/icon.png')  # adjust path if needed
        action = QAction(icon, "HabTile", self.iface.mainWindow())
        action.setObjectName('habtile_action')
        action.setToolTip('HabTile — create 256x256 habitat classification tiles')
        action.triggered.connect(self.run)  # your existing run method
        self.select_layer_action = QAction("Select Habitat Layer", self.iface.mainWindow())
        self.select_layer_action.setToolTip("Choose which habitat layer to use")
        self.select_layer_action.triggered.connect(self.select_habitat_layer)
        self.iface.addPluginToMenu(self.menu, self.select_layer_action)
        self.actions.append(self.select_layer_action)


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

    def select_habitat_layer(self):
        dlg = HabitatLayerSelector()
        if dlg.exec_() == QDialog.Accepted:
            selected = dlg.selected_layer()
            if selected:
                self.selected_habitat_layer = selected
                if self.tool:
                    self.tool.habitat_layer = selected
                    self.tool.set_symbology()
                    self.tool.configure_attribute_form()
                QMessageBox.information(None, "Layer Selected", f"Habitat layer set to: {selected.name()}")
            else:
                QMessageBox.warning(None, "No Layer", "No habitat layer selected.")

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
            self.tool = HabTile(self.iface.mapCanvas(), self.selected_habitat_layer)
            if self.tool.habitat_layer:
                self.tool.set_symbology()
                self.tool.configure_attribute_form()
        
        self.iface.mapCanvas().setMapTool(self.tool)
        
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
        raster_name = feature["source_raster"]
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




from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QComboBox, QPushButton, QLabel

class HabitatLayerSelector(QDialog):
    REQUIRED_FIELDS = [
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Habitat Layer")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Choose a habitat layer:"))
        self.combo = QComboBox()
        self.layer_map = {}
        for layer in QgsProject.instance().mapLayers().values():
            if (
                layer.type() == QgsMapLayer.VectorLayer
                and layer.geometryType() == QgsWkbTypes.PolygonGeometry
                and all(field in layer.fields().names() for field in self.REQUIRED_FIELDS)
            ):
                self.combo.addItem(layer.name())
                self.layer_map[layer.name()] = layer
        layout.addWidget(self.combo)
        btn = QPushButton("OK")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
        self.setLayout(layout)

    def selected_layer(self):
        name = self.combo.currentText()
        return self.layer_map.get(name, None)