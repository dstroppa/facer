import click
import botocore, botocore.session
from botocore.exceptions import ClientError
import time
import cv2
import sys
import errno
from os import listdir
from os.path import isfile, join

FILE_NAME = 'selfie.png'

def capture_frame():
    ### Capture image from cam
    camera = cv2.VideoCapture(0)
    time.sleep(0.2)  # If you don't wait, the image will be dark

    if camera.isOpened(): # try to get the first frame
        rval, frame = camera.read()
    else:
        rval = False
        exit -1

    cv2.imwrite(FILE_NAME, frame)
    del(camera)  # so that others can use the camera as soon as possible

def add_face(ctx, file, collection, name):
    session = botocore.session.Session(profile=ctx.obj['PROFILE'])

    ### Send to Rekognition to add it to faces collection
    rekognition = session.create_client('rekognition')
    dynamodb = session.create_client('dynamodb')

    ### Read image from file system
    with open(file, 'rb') as image:
        response = rekognition.index_faces(
            CollectionId=collection,
            Image={
                'Bytes': image.read()
            }
        )

    ### If successful, add info in DDB
    if len(response['FaceRecords']) > 0:
        ddb_response = dynamodb.put_item(
            TableName=collection,
            Item={
                'face-id': {
                    'S': response['FaceRecords'][0]['Face']['FaceId'],
                },
                'name': {
                    'S': name,
                }
            }
        )
        click.secho("All done. {} has been successfully added.".format(name), fg='blue')
    else:
        click.secho("Sorry, something went wrong while adding {}. Try again or see an admin for help.".format(name), fg='yellow')

@click.group()
@click.option('--profile', metavar='AWS_PROFILE', default='default', envvar='AWS_DEFAULT_PROFILE',
              help='The name of the AWS profile to use. You can configure a profile with the AWS CLI command: aws configure --profile <profile_name>.')
@click.pass_context
def cli(ctx, profile):
    """TBD"""
    ctx.obj = {}
    ctx.obj['PROFILE'] = profile

@cli.command()
@click.option('--collection', prompt='Please enter the collection name', help='Name of the collection to add the faces to')
@click.option('--path', prompt='Please enter the path to the images', help='Path to a directory containing the faces images')
@click.pass_context
def setup(ctx, collection, path):
    """Sets up a collection with faces (pictures) from the local filesystem."""
    session = botocore.session.Session(profile=ctx.obj['PROFILE'])

    rekognition = session.create_client('rekognition')
    dynamodb = session.create_client('dynamodb')

    ### Creates DDB table
    try:
        response = dynamodb.create_table(
            AttributeDefinitions=[
                {
                    'AttributeName': 'face-id',
                    'AttributeType': 'S',
                }
            ],
            KeySchema=[
                {
                    'AttributeName': 'face-id',
                    'KeyType': 'HASH',
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5,
            },
            TableName=collection
        )

        click.secho("DynamoDB table {} created.".format(collection), fg='blue')
    except ClientError as e:
        click.secho("Sorry, something went wrong: {}. Try again or see an admin for help.".format(e), fg='yellow')

    ### Creates Rekognition collection
    response = rekognition.create_collection(
        CollectionId=collection
    )

    if response['StatusCode'] == 200:
        click.secho("Collection {} created.".format(collection), fg='blue')
    else:
        click.secho("Sorry, something went wrong. Try again or see an admin for help.", fg='yellow')

    ### Adds faces to collection and info to DDB
    faces = [f for f in listdir(path) if isfile(join(path, f))]
    for face in faces:
        click.secho("Working on {}".format(face), fg='blue')
        try:
            add_face(ctx, join(path, face), collection, face.split('.')[0])
        except IOError as exc:
            if exc.errno != errno.EISDIR: # Do not fail if a directory is found, just ignore it.
                raise # Propagate other kinds of IOError.

@cli.command()
@click.option('--name', nargs=2, prompt='Please enter the full name', help='Full name of the person being added')
@click.option('--collection', prompt='Please enter the collection name', help='Name of the collection to add the face to')
@click.pass_context
def add(ctx, name, collection):
    """Captures an image from the camera and adds it to the collection."""
    ### Capture image from cam
    capture_frame()

    ### Send to Rekognition to add it to faces collection
    add_face(ctx, FILE_NAME, collection, name)


@cli.command()
@click.option('--collection', prompt='Please enter the collection name', help='Name of the collection to compare the face to')
@click.pass_context
def capture(ctx, collection):
    """Captures an image from the camera and compares it to the faces in the collection."""
    session = botocore.session.Session(profile=ctx.obj['PROFILE'])
    ### Capture image from cam
    capture_frame()

    ### Send to Rekognition to compare it to faces in collection
    rekognition = session.create_client('rekognition')
    dynamodb = session.create_client('dynamodb')

    with open("selfie.png", 'rb') as image:
        response = rekognition.search_faces_by_image(
            CollectionId=collection,
            Image={
                'Bytes': image.read()
            },
            MaxFaces=1,
            FaceMatchThreshold=80
        )

    ### If a match is found, get info from DDB
    if len(response['FaceMatches']) == 1:
        ddb_response = dynamodb.get_item(
            TableName=collection,
            Key={
                'face-id': {
                    'S': response['FaceMatches'][0]['Face']['FaceId'],
                }
            }
        )
        click.secho("Welcome {}! You can now proceed.".format(ddb_response['Item']['name']['S']), fg='green')
    else:
        click.secho("Sorry, we couldn't recognize you. Try again or see an admin for help.", fg='yellow')
