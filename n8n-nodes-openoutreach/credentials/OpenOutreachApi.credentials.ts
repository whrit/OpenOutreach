import {
  ICredentialType,
  INodeProperties,
} from 'n8n-workflow';

export class OpenOutreachApi implements ICredentialType {
  name = 'openOutreachApi';
  displayName = 'OpenOutreach API';
  documentationUrl = 'https://github.com/eracle/OpenOutreach';
  properties: INodeProperties[] = [
    {
      displayName: 'Base URL',
      name: 'baseUrl',
      type: 'string',
      default: 'https://openoutreach.example.com',
      placeholder: 'https://your-openoutreach-host.com',
      description: 'The URL where your OpenOutreach instance is running',
    },
    {
      displayName: 'API Key',
      name: 'apiKey',
      type: 'string',
      typeOptions: { password: true },
      default: '',
      description: 'API key from OpenOutreach Django Admin -> API Keys',
    },
  ];
}
