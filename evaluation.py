import os
import json
import multiprocessing as mp
import traceback
import logging
import skimage
import numpy as np
import cv2 as cv
import helpers as h
from algorithms import Felzenszwalb, Slic, Watershed

ROOT_DIR = os.path.abspath("")
images_dir = os.path.join(ROOT_DIR, "labeled_data", "groundtruths")
labels_dir = os.path.join(ROOT_DIR, "labeled_data", "labels")
results_dir = os.path.join(ROOT_DIR, "results")


def get_data(conv_function, width):
    annotations = [json.load(open(os.path.join(labels_dir, f))) for f in os.listdir(labels_dir) if os.path.isfile(os.path.join(labels_dir, f))]
    annotations = [a for a in annotations if a['shapes']]

    data = []
    # Add images
    for a in annotations:
        # Get the x, y coordinaets of points of the polygons that make up
        # the outline of each object instance. These are stores in the
        # shape_attributes (see json format above)

        image_path = os.path.join(images_dir, a['imagePath'])
        image = skimage.io.imread(image_path, plugin='pil')
        image = conv_function(image)
        #Get resize
        (H, W) = image.shape[:2]
        r = width / float(H)
        dim = (int(W * r), width)
        image = cv.resize(image, dim, interpolation=cv.INTER_AREA)

        polygons = [{'all_points_x': [int(p[0]*r) for p in shape['points']],
                     'all_points_y': [int(p[1]*r) for p in shape['points']]} \
                    for shape in a['shapes'] if shape['label'] == 'Post-It']
        (newH, newW) = image.shape[:2]
        mask = np.zeros([newH, newW], dtype=np.uint8)
        for i, p in enumerate(polygons, 1):
            # Get indexes of pixels inside the polygon and set them to 1
            rr, cc = skimage.draw.polygon(p['all_points_y'], p['all_points_x'])
            mask[rr, cc] = i
        data.append((image, mask))

    print("Prepared data.")
    return data


def evaluate(data):
    alg = Watershed(data[0])
    return alg.cross_evaluate(data[1])


def run_algorithm(data):
    # Parallelizing using Pool.apply()
    num_cpus = mp.cpu_count()

    # Step 1: Init multiprocessing.Pool()
    pool = mp.Pool(num_cpus)

    # Step 2: `pool.apply` the `howmany_within_range()`
    results = pool.map(evaluate, data)

    # Step 3: Don't forget to close
    pool.close()

    num_images = len(results)

    for i in range(len(results[0])):
        npri_sum = 0.0
        precision_sum = 0.0
        recall_sum = 0.0
        f_score_sum = 0.0

        for configurations in results:
            npri_sum += configurations[i]["npri_score"]
            precision_sum += configurations[i]["precision"]
            recall_sum += configurations[i]["recall"]
            f_score_sum += configurations[i]["f_score"]

        results[0][i]["npri_score"] = (npri_sum / num_images)
        results[0][i]["precision"] = (precision_sum / num_images)
        results[0][i]["recall"] = (recall_sum / num_images)
        results[0][i]["f_score"] = (f_score_sum / num_images)

    avg_results = sorted(results[0], key=lambda x: x["npri_score"], reverse=True)
    return avg_results


def write_data(avg_results, algorithm_name, colorspace):
    algorithm_dir = os.path.join(results_dir, algorithm_name)
    try:
        os.mkdir(algorithm_dir)
    except FileExistsError:
        pass
    results_file = os.path.join(algorithm_dir, f"{colorspace}.json")
    with open(results_file, 'w') as outfile:
        json.dump(avg_results, outfile)


if __name__ == '__main__':
    import argparse

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Run cross evaluation')
    parser.add_argument("algorithm",
                        metavar="<algorithm_name>",
                        help="Name of the algorithm e.g. felzenszwalb")
    parser.add_argument('--colorspace',
                        metavar="<colorspace_name>",
                        default=None,
                        help='Name of the colorspace to convert to e.g. BGR, YCrCb')
    parser.add_argument('--width',
                        metavar="<XXXX>",
                        default=512,
                        help='Image width for downscaling')
    args = parser.parse_args()

    colorspace2function = {
        'BGR': lambda x: cv.cvtColor(x, cv.COLOR_RGB2BGR),
        'Lab': lambda x: cv.cvtColor(x, cv.COLOR_RGB2Lab),
        'YCrCb': lambda x: cv.cvtColor(x, cv.COLOR_RGB2YCrCb),
        'HSV': lambda x: cv.cvtColor(x, cv.COLOR_RGB2HSV),
        'a*+b*': lambda x: h.create_sum_image(x, cv.COLOR_RGB2Lab),
        'Cr+Cb': lambda x: h.create_sum_image(x)
    }

    ### Special case if colorspaces == all
    if args.colorspace == 'all':
        for cspace in colorspace2function:
            try:
                data_pairs = get_data(colorspace2function[cspace], args.width)
                results = run_algorithm(data_pairs)
                write_data(results, args.algorithm, cspace)
                print(f"Cross validation successfull for colorspace {cspace}.")
            except Exception as e:
                print(f"[ERROR]: Cross validation failed for colorspace {cspace}.")
                logging.error(traceback.format_exc())
                # Logs the error appropriately.
                continue
    else:
        data_pairs = get_data(colorspace2function[args.colorspace], args.width)
        results = run_algorithm(data_pairs)
        write_data(results, args.algorithm, args.colorspace)
        print(f"Cross validation successfull for colorspace {args.colorspace}.")

