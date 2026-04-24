Estrategia de desarrollo del Hackathon Cassini:

Objetivo: crear un visor en tiempo real que te de la cobertura de nieve actual, a días vista (+24h, +48h, +72h) a semanas vista (+7días) y si los resultados del modelo son suficientemente buenos, a meses vista (+1mes, +2meses). 

Metodología: se entrenará un modelo ML (LSTM? Otro modelo? A tu decisión @Joan!) que use el NDSI como etiqueta a predecir (podemos plantearlo como 0=No nieve y 1=Nieve o predecir el valor de NDSI como tal que va de 0 a 1 también).

Features del visor:
- Mapa donde se muestran los COG seleccionados
- Panel lateral: aparecerá logo, seleccionable de la región montañosa (solo estará Sierra Nevada al principio), Indicador "Snow Cover", Indicador "Snow change", Stats (por cuenca hidrográfica), Dataset "Snow routes" (dentro habrá ski touring routes y snowshoe routes) donde habrá una serie de rutas "clásicas" de hacer en sierra nevada.
- Cuando una snow route es abierta, tienes la opción de poder cruzarla con la capa de "snow cover" que has elegido (p.ej. la capa +72h) y te dirá cuanto de %de nieve hay en la ruta que %de nieve no, te dibuja la ruta con las zonas concretas que no hay nieve y las que si (aplica la simbologia). 
- Cuando stats es abierto se te ofrecen todas las cuencas hidrográficas del sistema montañoso, y cuando seleccionas una te dibuja en el mapa esa cuenca y te dice el % de area cubierta de nieve, y la gráfica de tendencia tanto pasada como futura.
- Añadir créditos a Darwin Geospatial y poner enlace a la web (y logo).

Objetivos por persona:
- Joan: encárgate del modelo de machine learning, no te vuelvas loco en cuanto a complejidad, algo que te veas con garantías de sacar en 1 día. Si solo da tiempo a meter las imagenes de NDSI y entrenar con eso como veas, es mejor tener algo sencillo y terminado a algo hipercomplejo y que no podamos terminar para el domingo. Te dejo una serie de artículos que quizás puedes usar de inspiración para diseñar el modelo y datos a utilizar:

KiKeMerino / Sierra-CC — Snow Cover Forecasting with LSTM/NARX
https://github.com/KiKeMerino/sierra-cc

Repo muy alineado con vuestro caso: predice snow-covered area y probabilidad de nieve por píxel usando MODIS + variables meteorológicas. Entrena modelos NARX con capas LSTM, con limpieza/imputación de datos y tuning con Optuna.


Spatio-temporal prediction of snow cover in the Black Forest mountain range using remote sensing and a recurrent neural network
https://rmets.onlinelibrary.wiley.com/doi/abs/10.1002/joc.2043

Muy aplicable porque predice la cobertura de nieve futura en una zona montañosa usando datos de teledetección y una red neuronal recurrente, es decir, una lógica parecida a LSTM/series temporales espaciales.


Downscaling MODIS NDSI to Sentinel-2 fractional snow cover using random forest regression
https://www.tandfonline.com/doi/full/10.1080/2150704X.2024.2327084

Muy interesante para obtener cobertura fraccional de nieve a mayor resolución. Entrenan un Random Forest para modelar FSC de Sentinel-2 a partir de NDSI MODIS y variables auxiliares.


Leveraging advanced deep learning and machine learning approaches for daily snow depth prediction in the Atlas Mountains
https://www.sciencedirect.com/science/article/pii/S2214581824004348

No predice cobertura sino profundidad de nieve diaria, pero es muy útil porque combina variables nivales/meteorológicas y compara modelos ML/DL. Según el resumen, SVR obtuvo el mejor rendimiento, con RMSE de 2–5 cm y R² medio de 0.97.

- Mario: encargado del diseño de la aplicación, backend, frontend, product design.
- Guille: encargado del diseño de infraestructura. 

Cosas pendientes: dónde guardaremos los datos (backend) como se conectará con el frontend, infraestructura.

