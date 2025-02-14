import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, QWidget,
    QFileDialog, QMessageBox, QLabel, QListWidget, QListWidgetItem,
    QColorDialog, QSpinBox, QLineEdit, QGroupBox, QGridLayout, QStatusBar,
    QListView, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsItem, QGraphicsItemGroup, QSplitter,
    QSizePolicy, QGraphicsLineItem, QDialog, QRubberBand, QSlider
)
from PyQt5.QtGui import (
    QPixmap, QPainter, QPen, QColor, QFont, QIcon, QImage,
    QFontMetrics, QTransform, QCursor
)
from PyQt5.QtCore import (
    Qt, QPoint, QSize, QRectF, pyqtSignal, QThread, QObject,
    pyqtSlot, QBuffer, QRect, QEvent
)


class ThumbnailLoader(QObject):
    """异步加载缩略图的工作线程"""
    finished = pyqtSignal()
    thumbnail_loaded = pyqtSignal(str, QIcon)

    def __init__(self, file_paths, icon_size):
        super().__init__()
        self.file_paths = file_paths
        self.icon_size = icon_size
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        for file_path in self.file_paths:
            if not self.is_running:
                break
            pixmap = QPixmap(file_path).scaled(
                self.icon_size, self.icon_size,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon = QIcon(pixmap)
            self.thumbnail_loaded.emit(file_path, icon)
        self.finished.emit()


class ImageGraphicsView(QGraphicsView):
    annotations_changed = pyqtSignal()  # 通知主窗口更新标注列表

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # 包含图片和标注的组
        self.image_group = QGraphicsItemGroup()
        self.scene.addItem(self.image_group)

        self.image_item = None  # 原始图片的图形项
        self.annotations = []  # 存储所有的标注项
        self.prefix = "BR"
        self.num_digits = 2  # 序号位数，默认为2
        self.index = 1
        self.current_annotation_color = QColor(0, 0, 0)  # 当前标注颜色
        self.text_size = 100  # 标注字体大小
        self.id_text = ""
        self.id_text_size = 100  # ID字体大小
        self.id_color = QColor(0, 0, 0)  # ID颜色
        self.id_item = None  # ID标注的图形项

        # 固定水平绘制相关变量
        self.fixed_y_mode = False
        self.fixed_y_line = None  # 固定水平线的图形项
        self.fixed_y_line_fixed = False  # 跟踪水平线是否已固定

        # 标志位
        self.is_id_mode = False  # 是否为ID绘制模式

        # 缩放相关
        self.current_scale = 1.0  # 当前缩放比例

        # 悬浮标注项
        self.floating_annotation_item = None  # 用于显示悬浮的标注项

        # 可重用的编号列表
        self.available_indices = []

        # 背景颜色
        self.background_color = QColor(255, 255, 255)  # 默认白色

        # 启用鼠标跟踪
        self.setMouseTracking(True)

    def detect_background_color(self):
        """检测图像背景颜色，通过采样四个角的像素颜色并取平均"""
        if not self.image_item:
            self.background_color = QColor(255, 255, 255)  # 默认白色
            return

        pixmap = self.image_item.pixmap()
        image = pixmap.toImage()
        width = image.width()
        height = image.height()

        # 采样四个角
        colors = [
            QColor(image.pixel(0, 0)),
            QColor(image.pixel(width - 1, 0)),
            QColor(image.pixel(0, height - 1)),
            QColor(image.pixel(width - 1, height - 1))
        ]

        # 计算平均颜色
        avg_r = sum(color.red() for color in colors) // 4
        avg_g = sum(color.green() for color in colors) // 4
        avg_b = sum(color.blue() for color in colors) // 4

        self.background_color = QColor(avg_r, avg_g, avg_b)

    def load_pixmap(self, pixmap):
        if pixmap.isNull():
            QMessageBox.critical(self, "加载图片失败", "提供的图片为空。")
            return
        self.scene.clear()
        self.image_group = QGraphicsItemGroup()
        self.scene.addItem(self.image_group)

        self.image_item = QGraphicsPixmapItem(pixmap)
        self.image_item.setTransformationMode(Qt.SmoothTransformation)
        self.image_item.setTransformOriginPoint(
            pixmap.width() / 2, pixmap.height() / 2)
        self.image_item.setPos(
            -pixmap.width() / 2, -pixmap.height() / 2)
        self.image_group.addToGroup(self.image_item)

        self.annotations.clear()
        self.available_indices.clear()
        self.index = 1
        self.id_item = None
        self.fixed_y_line = None
        self.fixed_y_line_fixed = False
        self.image_group.setTransformOriginPoint(0, 0)
        self.setSceneRect(self.image_group.mapToScene(
            self.image_group.boundingRect()).boundingRect())
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        self.floating_annotation_item = None  # 重置悬浮标注项

        # 检测背景颜色
        self.detect_background_color()

        self.annotations_changed.emit()

    def set_prefix(self, prefix):
        self.prefix = prefix
        for i, item in enumerate(self.annotations, start=1):
            text = f"{self.prefix}{str(i).zfill(self.num_digits)}"
            item.setPlainText(text)
        # 更新悬浮标注的文本
        if self.floating_annotation_item and not self.is_id_mode:
            if self.available_indices:
                num = self.available_indices[0]
            else:
                num = self.index
            text = f"{self.prefix}{str(num).zfill(self.num_digits)}"
            self.floating_annotation_item.setPlainText(text)
        self.annotations_changed.emit()

    def set_num_digits(self, num_digits):
        self.num_digits = num_digits
        for i, item in enumerate(self.annotations, start=1):
            text = f"{self.prefix}{str(i).zfill(self.num_digits)}"
            item.setPlainText(text)
        # 更新悬浮标注的文本
        if self.floating_annotation_item and not self.is_id_mode:
            if self.available_indices:
                num = self.available_indices[0]
            else:
                num = self.index
            text = f"{self.prefix}{str(num).zfill(self.num_digits)}"
            self.floating_annotation_item.setPlainText(text)
        self.annotations_changed.emit()

    def set_current_annotation_color(self, color):
        self.current_annotation_color = color
        # 更新悬浮标注的颜色
        if self.floating_annotation_item and not self.is_id_mode:
            self.floating_annotation_item.setDefaultTextColor(color)

    def set_text_size(self, size):
        self.text_size = size
        for item in self.annotations:
            font = item.font()
            font.setPointSize(size)
            item.setFont(font)
        # 更新悬浮标注的字体大小
        if self.floating_annotation_item and not self.is_id_mode:
            font = self.floating_annotation_item.font()
            font.setPointSize(size)
            self.floating_annotation_item.setFont(font)
        self.annotations_changed.emit()

    def set_id_text(self, id_text):
        self.id_text = "ID:" + id_text
        if self.id_item:
            self.id_item.setPlainText(self.id_text)
        # 更新悬浮ID标注的文本
        if self.floating_annotation_item and self.is_id_mode:
            self.floating_annotation_item.setPlainText(self.id_text)
        self.annotations_changed.emit()

    def set_id_text_size(self, size):
        self.id_text_size = size
        if self.id_item:
            font = self.id_item.font()
            font.setPointSize(size)
            self.id_item.setFont(font)
        # 更新悬浮ID标注的字体大小
        if self.floating_annotation_item and self.is_id_mode:
            font = self.floating_annotation_item.font()
            font.setPointSize(size)
            self.floating_annotation_item.setFont(font)
        self.annotations_changed.emit()

    def set_id_color(self, color):
        self.id_color = color
        if self.id_item:
            self.id_item.setDefaultTextColor(color)
        # 更新悬浮ID标注的颜色
        if self.floating_annotation_item and self.is_id_mode:
            self.floating_annotation_item.setDefaultTextColor(color)
        self.annotations_changed.emit()

    def undo_last_annotation(self):
        if self.annotations:
            last_item = self.annotations.pop()
            # 提取编号
            text = last_item.toPlainText()
            if text.startswith(self.prefix):
                try:
                    num = int(text[len(self.prefix):])
                    if num not in self.available_indices:
                        self.available_indices.append(num)
                        self.available_indices.sort()
                except ValueError:
                    pass
            self.scene.removeItem(last_item)
            self.annotations_changed.emit()
        else:
            QMessageBox.information(self, "撤销", "没有可以撤销的操作。")

    def finalize_annotation(self, position, annotation_type='normal'):
        if annotation_type == 'normal':
            if self.available_indices:
                num = self.available_indices.pop(0)
            else:
                num = self.index
                self.index += 1
            annotation_text = f"{self.prefix}{str(num).zfill(self.num_digits)}"
            font_size = self.text_size
            color = self.current_annotation_color
        elif annotation_type == 'id':
            annotation_text = self.id_text
            font_size = self.id_text_size
            color = self.id_color
            if self.id_item:
                self.id_item.setParentItem(None)
                self.scene.removeItem(self.id_item)
                self.id_item = None
        else:
            return

        text_item = QGraphicsTextItem(annotation_text)
        font = QFont('Arial', font_size)
        font.setKerning(True)
        text_item.setFont(font)
        text_item.setDefaultTextColor(color)
        text_item.setParentItem(self.image_item)

        if self.fixed_y_mode and self.fixed_y_line:
            y_position = self.fixed_y_line.line().y1()
            font_metrics = QFontMetrics(font)
            text_height = font_metrics.height()
            position.setY(y_position - text_height)
        text_item.setPos(position)
        text_item.setFlag(QGraphicsItem.ItemIsSelectable, True)
        text_item.setData(0, annotation_type)

        if annotation_type == 'id':
            self.id_item = text_item
        else:
            self.annotations.append(text_item)
        self.annotations_changed.emit()

    def set_fixed_y_mode(self, mode: bool):
        self.fixed_y_mode = mode
        self.fixed_y_line_fixed = False
        if not mode and self.fixed_y_line:
            self.scene.removeItem(self.fixed_y_line)
            self.fixed_y_line = None
        # 移除悬浮标注项
        if self.floating_annotation_item:
            self.floating_annotation_item.setParentItem(None)
            self.scene.removeItem(self.floating_annotation_item)
            self.floating_annotation_item = None

    def set_fixed_y_position(self, y_position: float):
        if not self.image_item:
            return
        if not self.fixed_y_line:
            line = QGraphicsLineItem(
                self.image_item.boundingRect().left(), y_position,
                self.image_item.boundingRect().right(), y_position
            )
            line.setPen(QPen(Qt.red, 2, Qt.DashLine))
            line.setParentItem(self.image_item)
            self.fixed_y_line = line
        else:
            self.fixed_y_line.setLine(
                self.image_item.boundingRect().left(), y_position,
                self.image_item.boundingRect().right(), y_position
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.fixed_y_mode:
                if not self.fixed_y_line_fixed:
                    # 固定水平线
                    self.fixed_y_line_fixed = True
                    if self.fixed_y_line:
                        self.fixed_y_line.setPen(QPen(Qt.green, 2, Qt.DashLine))
                else:
                    # 固定悬浮标注项
                    if self.floating_annotation_item:
                        position = self.floating_annotation_item.pos()
                        if self.is_id_mode:
                            annotation_type = 'id'
                        else:
                            annotation_type = 'normal'
                        self.finalize_annotation(position, annotation_type)
                        # 移除悬浮标注项
                        self.floating_annotation_item.setParentItem(None)
                        self.scene.removeItem(self.floating_annotation_item)
                        self.floating_annotation_item = None
            else:
                # 固定悬浮标注项
                if self.floating_annotation_item:
                    position = self.floating_annotation_item.pos()
                    if self.is_id_mode:
                        annotation_type = 'id'
                    else:
                        annotation_type = 'normal'
                    self.finalize_annotation(position, annotation_type)
                    # 移除悬浮标注项
                    self.floating_annotation_item.setParentItem(None)
                    self.scene.removeItem(self.floating_annotation_item)
                    self.floating_annotation_item = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.image_item:
            super().mouseMoveEvent(event)
            return

        scene_pos = self.mapToScene(event.pos())
        group_pos = self.image_group.mapFromScene(scene_pos)
        image_pos = self.image_item.mapFromParent(group_pos)

        if self.fixed_y_mode and not self.fixed_y_line_fixed:
            # 更新固定水平线的位置
            self.set_fixed_y_position(image_pos.y())
            # 移除悬浮标注项
            if self.floating_annotation_item:
                self.floating_annotation_item.setParentItem(None)
                self.scene.removeItem(self.floating_annotation_item)
                self.floating_annotation_item = None
        else:
            # 创建或更新悬浮标注项
            if not self.floating_annotation_item:
                if self.is_id_mode:
                    text = self.id_text
                    font_size = self.id_text_size
                    color = self.id_color
                else:
                    if self.available_indices:
                        num = self.available_indices[0]
                    else:
                        num = self.index
                    text = f"{self.prefix}{str(num).zfill(self.num_digits)}"
                    font_size = self.text_size
                    color = self.current_annotation_color

                self.floating_annotation_item = QGraphicsTextItem(text)
                font = QFont('Arial', font_size)
                font.setKerning(True)
                self.floating_annotation_item.setFont(font)
                self.floating_annotation_item.setDefaultTextColor(color)
                self.floating_annotation_item.setParentItem(
                    self.image_item)
                self.floating_annotation_item.setFlag(
                    QGraphicsItem.ItemIsSelectable, True)

            # 更新悬浮标注项的位置
            position = image_pos
            if self.fixed_y_mode and self.fixed_y_line_fixed \
                    and self.fixed_y_line:
                y_position = self.fixed_y_line.line().y1()
                font_metrics = QFontMetrics(
                    self.floating_annotation_item.font())
                text_height = font_metrics.height()
                position.setY(y_position - text_height)
            self.floating_annotation_item.setPos(position)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)

    def save_image(self, save_path):
        if not self.image_item:
            return False

        # 临时隐藏悬浮的标注和未固定的水平线
        items_to_hide = []
        if self.floating_annotation_item:
            self.floating_annotation_item.setVisible(False)
            items_to_hide.append(self.floating_annotation_item)
        if self.fixed_y_line and not self.fixed_y_line_fixed:
            self.fixed_y_line.setVisible(False)
            items_to_hide.append(self.fixed_y_line)

        try:
            rect = self.image_group.mapToScene(
                self.image_group.boundingRect()).boundingRect()
            image = QImage(rect.size().toSize(), QImage.Format_RGB32)
            image.fill(self.background_color)  # 填充背景颜色
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            self.scene.render(painter, QRectF(image.rect()), rect)
            painter.end()

            # 检查图片格式，默认保存为JPEG
            format = "JPEG"
            if save_path.lower().endswith(".png"):
                format = "PNG"

            # 保存到内存中，检查大小
            buffer = QBuffer()
            buffer.open(QBuffer.ReadWrite)
            quality = 100
            while quality >= 10:
                buffer.seek(0)
                buffer.buffer().clear()
                if image.save(buffer, format, quality):
                    size_kb = buffer.size() / 1024
                    if size_kb <= 800:
                        with open(save_path, 'wb') as f:
                            f.write(buffer.data())
                        return True
                quality -= 10
            # 如果最低质量仍然大于800KB，强制保存
            return image.save(save_path, format, quality=10)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存图片时出错: {str(e)}")
            return False
        finally:
            # 恢复可见性
            for item in items_to_hide:
                item.setVisible(True)


class ImageEditorDialog(QDialog):
    """图片编辑对话框，提供旋转、翻转和裁剪功能，并增加撤销功能"""
    edited_pixmap = pyqtSignal(QPixmap)

    def __init__(self, pixmap, background_color, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片编辑")
        self.resize(900, 800)
        self.original_pixmap = pixmap
        self.base_pixmap = pixmap.copy()  # 基础图像，用于旋转
        self.current_pixmap = pixmap.copy()
        self.rotation_angle = 0  # 当前旋转角度
        self.history_stack = []  # 操作历史堆栈
        self.background_color = background_color  # 背景颜色

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setPixmap(self.current_pixmap)
        self.image_label.setScaledContents(True)
        self.image_label.setMinimumSize(800, 600)

        # 编辑按钮
        self.rotate_left_button = QPushButton("左旋转90°")
        self.rotate_right_button = QPushButton("右旋转90°")
        self.flip_horizontal_button = QPushButton("水平翻转")
        self.flip_vertical_button = QPushButton("垂直翻转")
        self.crop_button = QPushButton("裁剪")
        self.confirm_crop_button = QPushButton("✔")  # 对勾按钮
        self.confirm_crop_button.setToolTip("确认裁剪")
        self.confirm_crop_button.setVisible(False)  # 初始隐藏
        self.undo_button = QPushButton("撤销")
        self.save_button = QPushButton("保存")
        self.cancel_button = QPushButton("取消")

        # 手动旋转滑动条
        self.rotation_slider = QSlider(Qt.Horizontal)
        self.rotation_slider.setRange(-180, 180)
        self.rotation_slider.setValue(0)
        self.rotation_slider.setTickInterval(10)
        self.rotation_slider.setTickPosition(QSlider.TicksBelow)
        self.rotation_label = QLabel("旋转角度: 0°")

        # 状态标签
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignLeft)
        self.status_label.setStyleSheet("color: red;")

        # 布局
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.rotate_left_button)
        button_layout.addWidget(self.rotate_right_button)
        button_layout.addWidget(self.flip_horizontal_button)
        button_layout.addWidget(self.flip_vertical_button)
        button_layout.addWidget(self.crop_button)
        button_layout.addWidget(self.confirm_crop_button)  # 添加确认裁剪按钮
        button_layout.addWidget(self.undo_button)

        rotation_layout = QHBoxLayout()
        rotation_layout.addWidget(QLabel("手动旋转:"))
        rotation_layout.addWidget(self.rotation_slider)
        rotation_layout.addWidget(self.rotation_label)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.save_button)
        bottom_layout.addWidget(self.cancel_button)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.image_label)
        main_layout.addLayout(button_layout)
        main_layout.addLayout(rotation_layout)
        main_layout.addLayout(bottom_layout)
        main_layout.addWidget(self.status_label)  # 添加状态标签

        self.setLayout(main_layout)

        # 连接信号
        self.rotate_left_button.clicked.connect(self.rotate_left)
        self.rotate_right_button.clicked.connect(self.rotate_right)
        self.flip_horizontal_button.clicked.connect(self.flip_horizontal)
        self.flip_vertical_button.clicked.connect(self.flip_vertical)
        self.crop_button.clicked.connect(self.toggle_crop_mode)
        self.confirm_crop_button.clicked.connect(self.apply_crop)
        self.undo_button.clicked.connect(self.undo_operation)
        self.save_button.clicked.connect(self.save_edits)
        self.cancel_button.clicked.connect(self.reject)
        self.rotation_slider.valueChanged.connect(self.manual_rotate)
        self.rotation_slider.sliderPressed.connect(self.manual_rotate_start)
        self.rotation_slider.sliderReleased.connect(self.manual_rotate_end)

        # 裁剪相关
        self.cropping = False
        self.rubber_band = QRubberBand(QRubberBand.Rectangle, self.image_label)
        self.origin = QPoint()
        self.crop_rect = QRect()
        self.manual_rotate_previous_pixmap = None

    def rotate_pixmap(self, angle):
        """根据累积旋转角度旋转图像并使用背景颜色填充空白区域"""
        try:
            transform = QTransform().rotate(angle)
            rotated_pixmap = self.base_pixmap.transformed(transform, Qt.SmoothTransformation)
            # 计算旋转后的边界矩形
            rotated_rect = rotated_pixmap.rect()
            # 创建一个新的 QPixmap，填充背景颜色
            final_pixmap = QPixmap(rotated_rect.size())
            final_pixmap.fill(self.background_color)
            # 将旋转后的图像绘制到新的 QPixmap 上
            painter = QPainter(final_pixmap)
            painter.drawPixmap(0, 0, rotated_pixmap)
            painter.end()
            self.current_pixmap = final_pixmap
            self.image_label.setPixmap(self.current_pixmap)
        except Exception as e:
            QMessageBox.critical(self, "旋转失败", f"旋转图片时出错: {str(e)}")

    def rotate_left(self):
        """左旋转90°"""
        try:
            self.history_stack.append(self.base_pixmap.copy())
            self.rotation_angle -= 90
            if self.rotation_angle < -180:
                self.rotation_angle += 360
            self.rotation_slider.blockSignals(True)
            self.rotation_slider.setValue(self.rotation_angle)
            self.rotation_slider.blockSignals(False)
            self.rotation_label.setText(f"旋转角度: {self.rotation_angle}°")
            self.rotate_pixmap(self.rotation_angle)
            self.status_label.setText("")
        except Exception as e:
            QMessageBox.critical(self, "旋转失败", f"旋转图片时出错: {str(e)}")

    def rotate_right(self):
        """右旋转90°"""
        try:
            self.history_stack.append(self.base_pixmap.copy())
            self.rotation_angle += 90
            if self.rotation_angle > 180:
                self.rotation_angle -= 360
            self.rotation_slider.blockSignals(True)
            self.rotation_slider.setValue(self.rotation_angle)
            self.rotation_slider.blockSignals(False)
            self.rotation_label.setText(f"旋转角度: {self.rotation_angle}°")
            self.rotate_pixmap(self.rotation_angle)
            self.status_label.setText("")
        except Exception as e:
            QMessageBox.critical(self, "旋转失败", f"旋转图片时出错: {str(e)}")

    def flip_horizontal(self):
        """水平翻转"""
        try:
            self.history_stack.append(self.base_pixmap.copy())
            self.base_pixmap = self.base_pixmap.transformed(QTransform().scale(-1, 1), Qt.SmoothTransformation)
            self.rotate_pixmap(self.rotation_angle)  # 重新应用当前旋转角度
            self.status_label.setText("")
        except Exception as e:
            QMessageBox.critical(self, "翻转失败", f"翻转图片时出错: {str(e)}")

    def flip_vertical(self):
        """垂直翻转"""
        try:
            self.history_stack.append(self.base_pixmap.copy())
            self.base_pixmap = self.base_pixmap.transformed(QTransform().scale(1, -1), Qt.SmoothTransformation)
            self.rotate_pixmap(self.rotation_angle)  # 重新应用当前旋转角度
            self.status_label.setText("")
        except Exception as e:
            QMessageBox.critical(self, "翻转失败", f"翻转图片时出错: {str(e)}")

    def manual_rotate_start(self):
        """手动旋转开始，保存当前状态"""
        self.manual_rotate_previous_pixmap = self.base_pixmap.copy()

    def manual_rotate_end(self):
        """手动旋转结束，保存状态到历史堆栈"""
        if self.manual_rotate_previous_pixmap:
            self.history_stack.append(self.manual_rotate_previous_pixmap)
            self.manual_rotate_previous_pixmap = None

    def manual_rotate(self, angle):
        """手动自由旋转"""
        try:
            # 不将每次旋转加入历史堆栈，避免过多数据
            self.rotation_angle = angle
            self.rotation_label.setText(f"旋转角度: {angle}°")
            self.rotate_pixmap(angle)
            self.status_label.setText("")
        except Exception as e:
            QMessageBox.critical(self, "旋转失败", f"手动旋转时出错: {str(e)}")

    def toggle_crop_mode(self):
        """切换裁剪模式"""
        if not self.cropping:
            # 进入裁剪模式
            self.cropping = True
            self.crop_rect = QRect()
            self.rubber_band.setGeometry(QRect())
            self.rubber_band.show()
            self.confirm_crop_button.setVisible(True)
            self.image_label.installEventFilter(self)
            self.setCursor(QCursor(Qt.CrossCursor))
            self.status_label.setText("裁剪模式已启用，拖动鼠标选择裁剪区域。")
        else:
            # 退出裁剪模式
            self.cropping = False
            self.rubber_band.hide()
            self.confirm_crop_button.setVisible(False)
            self.image_label.removeEventFilter(self)
            self.setCursor(QCursor(Qt.ArrowCursor))
            self.status_label.setText("裁剪模式已关闭。")

    def eventFilter(self, source, event):
        if self.cropping and source == self.image_label:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self.origin = event.pos()
                self.rubber_band.setGeometry(QRect(self.origin, QSize()))
                self.rubber_band.show()
                return True
            elif event.type() == QEvent.MouseMove and self.cropping:
                if not self.origin.isNull():
                    rect = QRect(self.origin, event.pos()).normalized()
                    self.rubber_band.setGeometry(rect)
                return True
            elif event.type() == QEvent.MouseButtonRelease and self.cropping:
                self.crop_rect = self.rubber_band.geometry()
                return True
        return super().eventFilter(source, event)

    def apply_crop(self):
        try:
            if self.crop_rect.isNull() or self.crop_rect.width() < 10 or self.crop_rect.height() < 10:
                QMessageBox.warning(self, "裁剪区域过小", "请选择一个较大的裁剪区域。")
                return
            # 保存当前状态到历史堆栈
            self.history_stack.append(self.base_pixmap.copy())

            # 计算裁剪区域对应的图像坐标
            label_size = self.image_label.size()
            pixmap_size = self.base_pixmap.size()
            scale_x = self.base_pixmap.width() / label_size.width()
            scale_y = self.base_pixmap.height() / label_size.height()
            x = int(self.crop_rect.x() * scale_x)
            y = int(self.crop_rect.y() * scale_y)
            w = int(self.crop_rect.width() * scale_x)
            h = int(self.crop_rect.height() * scale_y)
            # 确保裁剪区域在图像范围内
            x = max(0, x)
            y = max(0, y)
            w = min(w, self.base_pixmap.width() - x)
            h = min(h, self.base_pixmap.height() - y)
            cropped = self.base_pixmap.copy(x, y, w, h)
            self.base_pixmap = cropped
            self.rotate_pixmap(self.rotation_angle)  # 重新应用当前旋转角度
            # 重置旋转滑动条
            self.rotation_slider.blockSignals(True)
            self.rotation_slider.setValue(0)
            self.rotation_slider.blockSignals(False)
            self.rotation_label.setText("旋转角度: 0°")
            self.rotation_angle = 0

            # 退出裁剪模式
            self.cropping = False
            self.rubber_band.hide()
            self.confirm_crop_button.setVisible(False)
            self.image_label.removeEventFilter(self)
            self.setCursor(QCursor(Qt.ArrowCursor))

            self.status_label.setText("图片已裁剪。")
        except Exception as e:
            QMessageBox.critical(self, "裁剪失败", f"裁剪图片时出错: {str(e)}")

    def undo_operation(self):
        """撤销上一步的操作"""
        if self.history_stack:
            last_pixmap = self.history_stack.pop()
            self.base_pixmap = last_pixmap.copy()
            self.rotate_pixmap(self.rotation_angle)  # 重新应用当前旋转角度
            self.status_label.setText("已撤销上一步的操作。")
        else:
            QMessageBox.information(self, "撤销", "没有可以撤销的操作。")

    def save_edits(self):
        if self.current_pixmap.isNull():
            QMessageBox.warning(self, "保存失败", "当前图片为空，无法保存。")
            return
        self.edited_pixmap.emit(self.current_pixmap)
        self.accept()


class ImageAnnotator(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Image Annotator")
        self.setGeometry(100, 100, 1600, 1000)

        self.splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(self.splitter)

        self.control_panel = QGroupBox("控制面板")
        self.control_layout = QVBoxLayout()
        self.control_panel.setLayout(self.control_layout)
        self.splitter.addWidget(self.control_panel)
        self.control_panel.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.control_panel.setFixedWidth(300)  # 设置固定宽度

        self.image_view = ImageGraphicsView(self)
        self.splitter.addWidget(self.image_view)
        self.image_view.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.thumbnail_list = QListWidget()
        self.thumbnail_list.setIconSize(QSize(100, 100))
        self.thumbnail_list.setFixedWidth(200)
        self.thumbnail_list.setViewMode(QListView.IconMode)
        self.thumbnail_list.setResizeMode(QListWidget.Adjust)
        self.splitter.addWidget(self.thumbnail_list)
        self.thumbnail_list.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([300, 1200, 200])

        self.add_controls_to_panel()
        self.connect_signals()

        self.image_paths = []
        self.current_image_path = ""
        self.current_pixmap = QPixmap()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.apply_styles()

    def add_controls_to_panel(self):
        grid = QGridLayout()

        self.open_button = QPushButton("打开文件/文件夹")
        self.open_button.setToolTip("打开图片文件或文件夹")
        grid.addWidget(self.open_button, 0, 0, 1, 2)

        self.undo_button = QPushButton("撤销 (Ctrl+Z)")
        self.undo_button.setToolTip("撤销最后一个标注")
        self.undo_button.setShortcut("Ctrl+Z")
        grid.addWidget(self.undo_button, 1, 0, 1, 2)

        self.color_button = QPushButton("设置当前标注颜色")
        self.color_button.setToolTip("设置当前标注颜色")
        grid.addWidget(self.color_button, 2, 0, 1, 2)

        # 字体大小设置
        self.size_spinbox = QSpinBox()
        self.size_spinbox.setRange(1, 1000)  # 扩大范围
        self.size_spinbox.setValue(100)  # 设置初始值为100
        self.size_spinbox.setToolTip("设置标注字体大小")
        self.size_confirm_button = QPushButton("确定")
        self.size_confirm_button.setToolTip("确定字体大小")
        grid.addWidget(QLabel("字体大小:"), 3, 0)
        grid.addWidget(self.size_spinbox, 3, 1)
        grid.addWidget(self.size_confirm_button, 3, 2)

        # 标注设置组
        self.annotation_settings_group = QGroupBox("标注设置")
        annotation_layout = QGridLayout()
        self.prefix_label = QLabel("标注前缀:")
        self.prefix_input = QLineEdit()
        self.prefix_input.setText(self.image_view.prefix)
        self.prefix_confirm_button = QPushButton("确定")
        self.prefix_confirm_button.setToolTip("确定标注前缀")
        self.num_digits_label = QLabel("序号位数:")
        self.num_digits_spinbox = QSpinBox()
        self.num_digits_spinbox.setRange(1, 10)
        self.num_digits_spinbox.setValue(self.image_view.num_digits)
        self.num_digits_confirm_button = QPushButton("确定")
        self.num_digits_confirm_button.setToolTip("确定序号位数")
        annotation_layout.addWidget(self.prefix_label, 0, 0)
        annotation_layout.addWidget(self.prefix_input, 0, 1)
        annotation_layout.addWidget(self.prefix_confirm_button, 0, 2)
        annotation_layout.addWidget(self.num_digits_label, 1, 0)
        annotation_layout.addWidget(self.num_digits_spinbox, 1, 1)
        annotation_layout.addWidget(self.num_digits_confirm_button, 1, 2)
        self.annotation_settings_group.setLayout(annotation_layout)
        grid.addWidget(self.annotation_settings_group, 4, 0, 1, 3)

        # ID设置组
        self.id_group = QGroupBox("ID设置")
        id_layout = QVBoxLayout()
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("输入ID")
        self.add_id_button = QPushButton("添加ID")
        self.add_id_button.setToolTip("添加ID标注 (Ctrl+I)")
        self.add_id_button.setShortcut("Ctrl+I")
        self.id_size_spinbox = QSpinBox()
        self.id_size_spinbox.setRange(1, 1000)  # 扩大范围
        self.id_size_spinbox.setValue(100)  # 设置初始值为100
        self.id_size_spinbox.setToolTip("设置ID字体大小")
        self.id_size_confirm_button = QPushButton("确定")
        self.id_size_confirm_button.setToolTip("确定ID字体大小")
        self.id_color_button = QPushButton("设置ID颜色")
        self.id_color_button.setToolTip("设置ID标注颜色")
        self.end_id_button = QPushButton("结束ID绘制 (Ctrl+E)")
        self.end_id_button.setToolTip("结束ID绘制模式")
        self.end_id_button.setShortcut("Ctrl+E")
        self.delete_id_button = QPushButton("删除ID")
        self.delete_id_button.setToolTip("删除ID标注")
        id_layout.addWidget(self.id_input)
        id_layout.addWidget(self.add_id_button)
        id_layout.addWidget(QLabel("ID字体大小:"))
        id_layout.addWidget(self.id_size_spinbox)
        id_layout.addWidget(self.id_size_confirm_button)
        id_layout.addWidget(self.id_color_button)
        id_layout.addWidget(self.delete_id_button)
        id_layout.addWidget(self.end_id_button)
        self.id_group.setLayout(id_layout)
        grid.addWidget(self.id_group, 5, 0, 1, 3)

        # 固定水平绘制组
        self.fixed_y_group = QGroupBox("固定水平绘制")
        fixed_y_layout = QVBoxLayout()
        self.start_fixed_y_button = QPushButton("开始固定水平绘制 (Ctrl+F)")
        self.start_fixed_y_button.setToolTip("开始固定水平绘制模式")
        self.start_fixed_y_button.setShortcut("Ctrl+F")
        self.modify_fixed_y_button = QPushButton("修改水平线 (Ctrl+M)")
        self.modify_fixed_y_button.setToolTip("修改固定水平线位置")
        self.modify_fixed_y_button.setShortcut("Ctrl+M")
        self.close_fixed_y_button = QPushButton("关闭固定绘制 (Ctrl+Q)")
        self.close_fixed_y_button.setToolTip("关闭固定水平绘制模式")
        self.close_fixed_y_button.setShortcut("Ctrl+Q")
        fixed_y_layout.addWidget(self.start_fixed_y_button)
        fixed_y_layout.addWidget(self.modify_fixed_y_button)
        fixed_y_layout.addWidget(self.close_fixed_y_button)
        self.fixed_y_group.setLayout(fixed_y_layout)
        grid.addWidget(self.fixed_y_group, 6, 0, 1, 3)

        # 添加旋转剪辑按钮
        self.edit_button = QPushButton("旋转剪辑")
        self.edit_button.setToolTip("旋转、翻转和裁剪图片")
        grid.addWidget(self.edit_button, 7, 0, 1, 3)

        # 当前模式标签
        self.mode_label = QLabel("当前模式：普通标注")
        self.mode_label.setFont(QFont('Arial', 12, QFont.Bold))
        self.mode_label.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.mode_label, 8, 0, 1, 3)

        # 保存图片按钮
        self.save_button = QPushButton("保存图片 (Ctrl+P)")
        self.save_button.setToolTip("保存当前标注的图片")
        self.save_button.setShortcut("Ctrl+P")
        grid.addWidget(self.save_button, 9, 0, 1, 3)

        # 标注列表组
        self.annotations_group = QGroupBox("标注列表")
        annotations_layout = QVBoxLayout()
        self.annotations_list = QListWidget()
        annotations_layout.addWidget(self.annotations_list)
        self.change_annotation_color_button = QPushButton("更改标注颜色")
        self.delete_annotation_button = QPushButton("删除选中标注")
        annotations_layout.addWidget(self.change_annotation_color_button)
        annotations_layout.addWidget(self.delete_annotation_button)
        self.annotations_group.setLayout(annotations_layout)
        grid.addWidget(self.annotations_group, 10, 0, 1, 3)

        self.control_layout.addLayout(grid)
        self.control_layout.addStretch()

    def connect_signals(self):
        self.open_button.clicked.connect(self.open_file_or_folder)
        self.undo_button.clicked.connect(self.undo_annotation)
        self.save_button.clicked.connect(self.save_image)
        self.color_button.clicked.connect(self.choose_current_annotation_color)
        self.size_confirm_button.clicked.connect(self.set_text_size)
        self.thumbnail_list.itemClicked.connect(self.load_selected_image)
        self.add_id_button.clicked.connect(self.add_id)
        self.id_size_confirm_button.clicked.connect(self.set_id_text_size)
        self.id_color_button.clicked.connect(self.choose_id_color)
        self.start_fixed_y_button.clicked.connect(self.start_fixed_y_mode)
        self.modify_fixed_y_button.clicked.connect(self.modify_fixed_y_mode)
        self.close_fixed_y_button.clicked.connect(self.close_fixed_y_mode)
        self.end_id_button.clicked.connect(self.end_id_mode)
        self.delete_id_button.clicked.connect(self.delete_id)
        self.delete_annotation_button.clicked.connect(
            self.delete_selected_annotation)
        self.change_annotation_color_button.clicked.connect(
            self.change_selected_annotation_color)
        self.edit_button.clicked.connect(self.open_image_editor)
        self.image_view.annotations_changed.connect(
            self.update_annotations_list)
        self.prefix_confirm_button.clicked.connect(self.set_prefix)
        self.num_digits_confirm_button.clicked.connect(self.set_num_digits)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                text-align: center;
                text-decoration: none;
                font-size: 14px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3e8e41;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ccc;
                margin-top: 10px;
                padding: 10px;
            }
            QLabel {
                font-size: 14px;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #ccc;
            }
            QLineEdit {
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 4px;
            }
            QSpinBox {
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 4px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: #b0b0b0;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #4CAF50;
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
        """)

    def open_file_or_folder(self):
        msg_box = QMessageBox()
        msg_box.setWindowTitle("选择文件或文件夹")
        msg_box.setText("请选择打开方式：")
        open_files_button = msg_box.addButton(
            "打开文件", QMessageBox.AcceptRole)
        open_folder_button = msg_box.addButton(
            "打开文件夹", QMessageBox.AcceptRole)
        cancel_button = msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.exec_()

        if msg_box.clickedButton() == open_files_button:
            options = QFileDialog.Options()
            files, _ = QFileDialog.getOpenFileNames(
                self, "选择图片文件", "",
                "Image Files (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)",
                options=options
            )
            if files:
                self.image_paths = files
                self.populate_thumbnail_list(self.image_paths)
                if self.image_paths:
                    self.load_image(self.image_paths[0])
            else:
                QMessageBox.information(
                    self, "没有选择文件", "请选择一个或多个图片文件。")
        elif msg_box.clickedButton() == open_folder_button:
            folder = QFileDialog.getExistingDirectory(
                self, "选择包含图片的文件夹", "",
                options=QFileDialog.Options()
            )
            if folder:
                self.load_images_from_folder(folder)
            else:
                QMessageBox.information(
                    self, "没有选择文件夹", "请选择一个包含图片的文件夹。")
        else:
            pass

    def load_images_from_folder(self, folder):
        self.image_paths = []
        self.thumbnail_list.clear()

        image_extensions = ['.png', '.jpg', '.jpeg', '.bmp', '.gif']
        file_paths = []
        for filename in os.listdir(folder):
            if any(filename.lower().endswith(ext) for ext in image_extensions):
                file_paths.append(os.path.join(folder, filename))

        self.loader = ThumbnailLoader(file_paths, 100)
        self.thread = QThread()
        self.loader.moveToThread(self.thread)
        self.thread.started.connect(self.loader.run)
        self.loader.finished.connect(self.thread.quit)
        self.loader.finished.connect(self.loader.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.loader.thumbnail_loaded.connect(self.add_thumbnail_to_list)
        self.thread.start()

    @pyqtSlot(str, QIcon)
    def add_thumbnail_to_list(self, file_path, icon):
        item = QListWidgetItem(icon, os.path.basename(file_path))
        item.setData(Qt.UserRole, file_path)
        self.thumbnail_list.addItem(item)

    def populate_thumbnail_list(self, image_paths):
        self.thumbnail_list.clear()
        self.image_paths = []
        self.loader = ThumbnailLoader(image_paths, 100)
        self.thread = QThread()
        self.loader.moveToThread(self.thread)
        self.thread.started.connect(self.loader.run)
        self.loader.finished.connect(self.thread.quit)
        self.loader.finished.connect(self.loader.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.loader.thumbnail_loaded.connect(self.add_thumbnail_to_list)
        self.thread.start()

    def load_image(self, image_path):
        try:
            self.current_image_path = image_path
            self.current_pixmap = QPixmap(image_path)
            if self.current_pixmap.isNull():
                QMessageBox.critical(self, "加载图片失败", f"无法加载图片: {image_path}")
                return
            self.image_view.load_pixmap(self.current_pixmap)
            self.status_bar.showMessage(
                f"已加载图片: {os.path.basename(image_path)}", 5000)
            self.mode_label.setText("当前模式：普通标注")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载图片时出错：{str(e)}")

    def load_selected_image(self, item):
        image_path = item.data(Qt.UserRole)
        if image_path:
            self.load_image(image_path)

    def undo_annotation(self):
        self.image_view.undo_last_annotation()
        self.status_bar.showMessage("撤销最后一个标注", 3000)

    def save_image(self):
        if self.current_image_path:
            # 自动关闭固定水平绘制模式
            if self.image_view.fixed_y_mode:
                self.image_view.set_fixed_y_mode(False)
                self.status_bar.showMessage("固定水平绘制模式已关闭", 3000)
                self.mode_label.setText("当前模式：普通标注")
            success = self.image_view.save_image(self.current_image_path)
            if success:
                QMessageBox.information(
                    self, "保存成功",
                    f"图片已保存并覆盖原始图片: {self.current_image_path}")
            else:
                QMessageBox.warning(
                    self, "保存失败",
                    f"无法保存图片至 {self.current_image_path}")
        else:
            QMessageBox.warning(self, "保存失败", "没有加载任何图片。")

    def choose_current_annotation_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.image_view.set_current_annotation_color(color)
            self.status_bar.showMessage(
                f"当前标注颜色已设置为: {color.name()}", 3000)

    def set_text_size(self):
        size = self.size_spinbox.value()
        self.image_view.set_text_size(size)
        self.status_bar.showMessage(f"标注字体大小已设置为: {size}", 3000)

    def set_prefix(self):
        prefix = self.prefix_input.text()
        if prefix:
            self.image_view.set_prefix(prefix)
            self.status_bar.showMessage(f"标注前缀已设置为: {prefix}", 3000)
        else:
            QMessageBox.warning(self, "无效输入", "标注前缀不能为空。")

    def set_num_digits(self):
        value = self.num_digits_spinbox.value()
        self.image_view.set_num_digits(value)
        self.status_bar.showMessage(f"序号位数已设置为: {value}", 3000)

    def add_id(self):
        id_text = self.id_input.text().strip()
        if id_text:
            self.image_view.set_id_text(id_text)
            self.image_view.is_id_mode = True
            self.image_view.set_fixed_y_mode(False)
            self.status_bar.showMessage("进入ID绘制模式", 3000)
            self.mode_label.setText("当前模式：ID标注")
            # 移除悬浮标注项
            if self.image_view.floating_annotation_item:
                self.image_view.floating_annotation_item.setParentItem(None)
                self.image_view.scene.removeItem(
                    self.image_view.floating_annotation_item)
                self.image_view.floating_annotation_item = None
        else:
            QMessageBox.warning(self, "无效输入", "ID 不能为空。")

    def set_id_text_size(self):
        size = self.id_size_spinbox.value()
        self.image_view.set_id_text_size(size)
        self.status_bar.showMessage(f"ID字体大小已设置为: {size}", 3000)

    def choose_id_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.image_view.set_id_color(color)
            self.status_bar.showMessage(f"ID标注颜色已设置为: {color.name()}", 3000)

    def start_fixed_y_mode(self):
        if not self.image_view.fixed_y_mode:
            if self.image_view.is_id_mode:
                self.image_view.is_id_mode = False
                self.status_bar.showMessage("退出ID绘制模式", 3000)
                self.mode_label.setText("当前模式：固定水平绘制")
            self.image_view.set_fixed_y_mode(True)
            self.status_bar.showMessage("进入固定水平绘制模式", 3000)
            self.mode_label.setText("当前模式：固定水平绘制")
            # 移除悬浮标注项
            if self.image_view.floating_annotation_item:
                self.image_view.floating_annotation_item.setParentItem(None)
                self.image_view.scene.removeItem(
                    self.image_view.floating_annotation_item)
                self.image_view.floating_annotation_item = None
        else:
            QMessageBox.information(self, "已在固定模式", "当前已处于固定水平绘制模式。")

    def modify_fixed_y_mode(self):
        if self.image_view.fixed_y_mode:
            if self.image_view.fixed_y_line:
                self.image_view.fixed_y_line_fixed = False
                self.image_view.fixed_y_line.setPen(
                    QPen(Qt.red, 2, Qt.DashLine))
            self.status_bar.showMessage("固定水平线已置为可修改", 3000)
            self.mode_label.setText("当前模式：固定水平绘制 (可修改)")
        else:
            QMessageBox.warning(self, "未开启固定模式", "请先开启固定水平绘制模式。")

    def close_fixed_y_mode(self):
        if self.image_view.fixed_y_mode:
            self.image_view.set_fixed_y_mode(False)
            self.status_bar.showMessage("固定水平绘制模式已关闭", 3000)
            self.mode_label.setText("当前模式：普通标注")
        else:
            QMessageBox.warning(self, "未开启固定模式", "请先开启固定水平绘制模式。")

    def end_id_mode(self):
        if self.image_view.is_id_mode:
            self.image_view.is_id_mode = False
            self.status_bar.showMessage("退出ID绘制模式", 3000)
            self.mode_label.setText("当前模式：普通标注")
            # 移除悬浮标注项
            if self.image_view.floating_annotation_item:
                self.image_view.floating_annotation_item.setParentItem(None)
                self.image_view.scene.removeItem(
                    self.image_view.floating_annotation_item)
                self.image_view.floating_annotation_item = None
        else:
            QMessageBox.warning(self, "未开启ID模式", "当前未处于ID绘制模式。")

    def delete_id(self):
        if self.image_view.id_item:
            # 提取编号并添加到可重用列表
            text = self.image_view.id_item.toPlainText()
            if text.startswith("ID:"):
                try:
                    num = int(text[len("ID:"):])
                    if num not in self.image_view.available_indices:
                        self.image_view.available_indices.append(num)
                        self.image_view.available_indices.sort()
                except ValueError:
                    pass
            self.image_view.id_item.setParentItem(None)
            self.image_view.scene.removeItem(self.image_view.id_item)
            self.image_view.id_item = None
            self.image_view.annotations_changed.emit()
            self.status_bar.showMessage("ID标注已删除", 3000)
        else:
            QMessageBox.warning(self, "没有ID标注", "当前没有ID标注可以删除。")

    def update_annotations_list(self):
        self.annotations_list.clear()
        for item in self.image_view.annotations + \
                ([self.image_view.id_item] if self.image_view.id_item else []):
            if item:
                text = item.toPlainText()
                pos = item.pos()
                item_text = f"{text} at ({pos.x():.1f}, {pos.y():.1f})"
                list_item = QListWidgetItem(item_text)
                list_item.setData(Qt.UserRole, item)
                self.annotations_list.addItem(list_item)

    def delete_selected_annotation(self):
        selected_items = self.annotations_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "未选择标注", "请先选择要删除的标注。")
            return
        for list_item in selected_items:
            annotation_item = list_item.data(Qt.UserRole)
            if annotation_item:
                if annotation_item in self.image_view.annotations:
                    # 提取编号并添加到可重用列表
                    text = annotation_item.toPlainText()
                    if text.startswith(self.image_view.prefix):
                        try:
                            num = int(text[len(self.image_view.prefix):])
                            if num not in self.image_view.available_indices:
                                self.image_view.available_indices.append(num)
                                self.image_view.available_indices.sort()
                        except ValueError:
                            pass
                    self.image_view.annotations.remove(annotation_item)
                if annotation_item == self.image_view.id_item:
                    self.image_view.id_item = None
                annotation_item.setParentItem(None)
                self.image_view.scene.removeItem(annotation_item)
                self.annotations_list.takeItem(
                    self.annotations_list.row(list_item))
        self.image_view.annotations_changed.emit()
        self.status_bar.showMessage("选中的标注已删除", 3000)

    def change_selected_annotation_color(self):
        selected_items = self.annotations_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "未选择标注", "请先选择要更改颜色的标注。")
            return
        color = QColorDialog.getColor()
        if color.isValid():
            for list_item in selected_items:
                annotation_item = list_item.data(Qt.UserRole)
                if annotation_item:
                    annotation_item.setDefaultTextColor(color)
            self.status_bar.showMessage("选中标注的颜色已更改", 3000)

    def open_image_editor(self):
        if not self.current_image_path:
            QMessageBox.warning(self, "未加载图片", "请先加载一张图片。")
            return
        pixmap = self.current_pixmap.copy()
        if pixmap.isNull():
            QMessageBox.critical(self, "加载失败", "无法加载当前图片。")
            return
        dialog = ImageEditorDialog(pixmap, self.image_view.background_color, self)
        dialog.edited_pixmap.connect(self.apply_edited_pixmap)
        dialog.exec_()

    def apply_edited_pixmap(self, edited_pixmap):
        if not edited_pixmap.isNull():
            try:
                # 更新当前_pixmap为编辑后的副本
                self.current_pixmap = edited_pixmap
                # 重新加载图片到视图
                self.image_view.load_pixmap(self.current_pixmap)
                self.status_bar.showMessage("图片已编辑。请在主界面点击“保存图片”以覆盖原文件。", 5000)
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"应用编辑后的图片时出错: {str(e)}")
        else:
            QMessageBox.warning(self, "编辑失败", "编辑后的图片为空。")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = ImageAnnotator()
    main_window.show()
    sys.exit(app.exec_())
