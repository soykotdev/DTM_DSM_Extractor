from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer  # Add QgsRasterLayer here
from qgis.PyQt.QtWidgets import QAction, QFileDialog
import processing

class DSM_DTMExtractor:

    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()

    def initGui(self):
        # Add a toolbar button and menu item
        self.action = QAction("DSM, DTM extractor", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&DSM, DTM extractor", self.action)

    def unload(self):
        # Remove the plugin menu item and icon
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("&DSM, DTM extractor", self.action)

    def run(self):
        # Let the user select the input files
        centerline_path, _ = QFileDialog.getOpenFileName(None, "Select Centerline Shapefile", "", "Shapefiles (*.shp)")
        buffer_path, _ = QFileDialog.getOpenFileName(None, "Select Buffer Shapefile", "", "Shapefiles (*.shp)")
        dsm_raster_path, _ = QFileDialog.getOpenFileName(None, "Select DSM Raster", "", "Raster files (*.tif)")
        dtm_raster_path, _ = QFileDialog.getOpenFileName(None, "Select DTM Raster", "", "Raster files (*.tif)")

        if not all([centerline_path, buffer_path, dsm_raster_path, dtm_raster_path]):
            self.iface.messageBar().pushMessage("Error", "All inputs are required!", level=3)
            return

        # Load selected layers
        centerline_layer = QgsVectorLayer(centerline_path, "Centerline", "ogr")
        buffer_layer = QgsVectorLayer(buffer_path, "Buffer", "ogr")
        dsm_raster_layer = QgsRasterLayer(dsm_raster_path, "DSM")
        dtm_raster_layer = QgsRasterLayer(dtm_raster_path, "DTM")

        QgsProject.instance().addMapLayer(centerline_layer)
        QgsProject.instance().addMapLayer(buffer_layer)
        QgsProject.instance().addMapLayer(dsm_raster_layer)
        QgsProject.instance().addMapLayer(dtm_raster_layer)

        # Execute the processing steps as in your original script
        # Step 1: Buffer the centerline with 2m distance
        buffer_output = processing.run("native:buffer", {
            'INPUT': centerline_layer,
            'DISTANCE': 2,
            'SEGMENTS': 5,
            'END_CAP_STYLE': 0,
            'JOIN_STYLE': 0,
            'MITER_LIMIT': 2,
            'DISSOLVE': False,
            'OUTPUT': 'memory:'
        })['OUTPUT']

        # Step 2: Convert the buffered polygon to line features
        poly_to_line_output = processing.run("native:polygonstolines", {
            'INPUT': buffer_output,
            'OUTPUT': 'memory:'
        })['OUTPUT']

        # Step 3: Merge the converted line with the original centerline
        merge_output = processing.run("native:mergevectorlayers", {
            'LAYERS': [poly_to_line_output, centerline_layer],
            'CRS': centerline_layer.crs(),
            'OUTPUT': 'memory:'
        })['OUTPUT']

        # Step 4: Create points along the merged line geometry every 5m
        points_along_output = processing.run("native:pointsalonglines", {
            'INPUT': merge_output,
            'DISTANCE': 5,
            'START_OFFSET': 0,
            'END_OFFSET': 0,
            'OUTPUT': 'memory:'
        })['OUTPUT']

        # Step 5: Create a grid from buffer with 5m width and height, clipped to the shapefile
        grid_output = processing.run("native:creategrid", {
            'TYPE': 2,  # Rectangle (Polygon)
            'EXTENT': buffer_layer.extent(),
            'HSPACING': 5,
            'VSPACING': 5,
            'HOVERLAY': 0,
            'VOVERLAY': 0,
            'CRS': buffer_layer.crs(),
            'OUTPUT': 'memory:'
        })['OUTPUT']

        clipped_grid_output = processing.run("native:clip", {
            'INPUT': grid_output,
            'OVERLAY': buffer_layer,
            'OUTPUT': 'memory:'
        })['OUTPUT']

        # Step 6: Extract centroids of the grid and clip them to the buffer shapefile
        centroids_output = processing.run("native:centroids", {
            'INPUT': clipped_grid_output,
            'ALLPARTS': False,
            'OUTPUT': 'memory:'
        })['OUTPUT']

        clipped_centroid_output = processing.run("native:clip", {
            'INPUT': centroids_output,
            'OVERLAY': buffer_layer,
            'OUTPUT': 'memory:'
        })['OUTPUT']

        # Step 7: Select centroids by location (intersects buffer) and keep non-intersecting centroids
        processing.run("qgis:selectbylocation", {
            'INPUT': clipped_centroid_output,
            'PREDICATE': [0],  # Intersects
            'INTERSECT': buffer_output,
            'METHOD': 0  # Create new selection
        })

        # Invert selection to get non-intersecting centroids
        clipped_centroid_output.invertSelection()

        # Save the non-intersecting centroids
        remaining_centroids = processing.run("native:saveselectedfeatures", {
            'INPUT': clipped_centroid_output,
            'OUTPUT': 'memory:'
        })['OUTPUT']

        # Deselect all to avoid further issues
        clipped_centroid_output.removeSelection()

        # Step 8: Merge two vector layers (output from Step 4 and Step 7)
        merged_output = processing.run("native:mergevectorlayers", {
            'LAYERS': [points_along_output, remaining_centroids],
            'CRS': points_along_output.crs(),  # Use CRS from one of the input layers
            'OUTPUT': 'memory:'
        })['OUTPUT']

        # Set the final output layer name to 'merged_point'
        merged_output.setName("merged_point")

        # Add the final layer to the QGIS canvas
        QgsProject.instance().addMapLayer(merged_output)

        # Step 9: Add raster values to the merged points (DTM)
        raster_values_output_DTM = processing.run("sagang:addrastervaluestopoints", {
            'SHAPES': merged_output,
            'GRIDS': dtm_raster_layer,
            'RESULT': 'TEMPORARY_OUTPUT',
            'RESAMPLING': 3
        })['RESULT']

        result_layer_DTM = QgsVectorLayer(raster_values_output_DTM, "DTM", "ogr")
        QgsProject.instance().addMapLayer(result_layer_DTM)

        # Step 10: Add raster values to the merged points (DSM)
        raster_values_output_DSM = processing.run("sagang:addrastervaluestopoints", {
            'SHAPES': result_layer_DTM,
            'GRIDS': dsm_raster_layer,
            'RESULT': 'TEMPORARY_OUTPUT',
            'RESAMPLING': 3
        })['RESULT']

        result_layer_DSM = QgsVectorLayer(raster_values_output_DSM, "DSM", "ogr")
        QgsProject.instance().addMapLayer(result_layer_DSM)
