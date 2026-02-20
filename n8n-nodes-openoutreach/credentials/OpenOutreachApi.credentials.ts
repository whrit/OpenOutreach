import {
  IAuthenticateGeneric,
  ICredentialTestRequest,
  ICredentialType,
  INodeProperties,
} from 'n8n-workflow';

export class OpenOutreachApi implements ICredentialType {
  name = 'openOutreachApi';
  displayName = 'OpenOutreach API';
  documentationUrl = 'https://github.com/eracle/OpenOutreach';
  icon = 'file:openoutreach.svg' as const;
  authenticate: IAuthenticateGeneric = {
    type: 'generic',
    properties: {
      headers: {
        Authorization: '=Api-Key {{$credentials.apiKey}}',
      },
    },
  };
  test: ICredentialTestRequest = {
    request: {
      baseURL: '={{$credentials.baseUrl}}',
      url: '/api/v1/campaigns/',
    },
  };
  properties: INodeProperties[] = [
    {
      displayName: 'Base URL',
      name: 'baseUrl',
      type: 'string',
      required: true,
      default: 'https://openoutreach.example.com',
      placeholder: 'e.g. https://openoutreach.yourdomain.com',
      description: 'The URL where your OpenOutreach instance is running',
    },
    {
      displayName: 'API Key',
      name: 'apiKey',
      type: 'string',
      typeOptions: { password: true },
      required: true,
      default: '',
      description: 'API key from OpenOutreach Django Admin -> API Keys',
    },
  ];
}
