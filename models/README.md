# Models shipped with ShaydoxCut

`yamnet.onnx` and `yamnet_class_map.csv` are YAMNet, Google's sound-event model (AudioSet, 521 classes), converted to
ONNX. ShaydoxCut uses it to hear laughter, cheering and screaming. YAMNet is released by Google under the Apache
License 2.0: https://github.com/tensorflow/models/tree/master/research/audioset/yamnet

The other models (speech to text, the face finder) are downloaded by ShaydoxCut itself the first time they are needed.
